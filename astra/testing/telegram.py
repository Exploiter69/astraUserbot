"""Deterministic fake Telegram client/event and real-wrapper command dispatch.

These helpers model only the Telegram surface explicitly supported here. They
do not implement or emulate the Phase 4 capability layer.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class RecordedEffect:
    operation: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    order: int
    result: Any = None
    exception: str | None = None


class _EffectRecorder:
    def __init__(self) -> None:
        self.effects: list[RecordedEffect] = []

    async def record(
        self,
        operation: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        action: Callable[[], Any] | None = None,
    ) -> Any:
        try:
            result = action() if action is not None else None
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            self.effects.append(
                RecordedEffect(
                    operation=operation,
                    args=args,
                    kwargs=dict(kwargs),
                    order=len(self.effects) + 1,
                    exception=f"{type(exc).__name__}: {exc}",
                )
            )
            raise
        self.effects.append(
            RecordedEffect(
                operation=operation,
                args=args,
                kwargs=dict(kwargs),
                order=len(self.effects) + 1,
                result=result,
            )
        )
        return result


class FakeTelegramClient:
    """Client-shaped fake implementing Telethon handler registration and writes."""

    def __init__(self) -> None:
        self.handlers: list[tuple[Callable[..., Any], Any]] = []
        self._recorder = _EffectRecorder()

    @property
    def effects(self) -> tuple[RecordedEffect, ...]:
        return tuple(self._recorder.effects)

    def add_event_handler(self, handler: Callable[..., Any], builder: Any) -> None:
        self.handlers.append((handler, builder))

    def remove_event_handler(self, handler: Callable[..., Any], builder: Any) -> int:
        before = len(self.handlers)
        self.handlers = [pair for pair in self.handlers if pair != (handler, builder)]
        return before - len(self.handlers)

    async def send_message(self, *args: Any, **kwargs: Any) -> None:
        return await self._recorder.record("client.send_message", args, kwargs)

    async def edit_message(self, *args: Any, **kwargs: Any) -> None:
        return await self._recorder.record("client.edit_message", args, kwargs)

    async def delete_messages(self, *args: Any, **kwargs: Any) -> None:
        return await self._recorder.record("client.delete_messages", args, kwargs)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        raise NotImplementedError(f"unsupported fake Telegram client method: {name}")


class FakeTelegramEvent:
    """Minimal synthetic event whose supported operations are explicitly recorded."""

    def __init__(
        self,
        text: str,
        *,
        client: FakeTelegramClient | None = None,
        pattern_match: re.Match[str] | None = None,
        out: bool = True,
        chat_id: int | str = 10001,
        sender_id: int | str = 10002,
        id: int = 1,
        recorder: _EffectRecorder | None = None,
    ) -> None:
        self.out = out
        self.pattern_match = pattern_match
        self.raw_text = text
        self.text = text
        self.chat_id = chat_id
        self.sender_id = sender_id
        self.id = id
        self.client = client
        self.message = SimpleNamespace(
            message=text, raw_text=text, text=text, chat_id=chat_id,
            sender_id=sender_id, id=id, out=out,
        )
        self._recorder = recorder or (client._recorder if client else _EffectRecorder())

    @property
    def effects(self) -> tuple[RecordedEffect, ...]:
        return tuple(self._recorder.effects)

    async def _record(
        self,
        operation: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        action: Callable[[], Any] | None = None,
    ) -> Any:
        return await self._recorder.record(operation, args, kwargs, action)

    async def edit(self, *args: Any, **kwargs: Any) -> Any:
        return await self._record("event.edit", args, kwargs)

    async def reply(self, *args: Any, **kwargs: Any) -> Any:
        return await self._record("event.reply", args, kwargs)

    async def delete(self, *args: Any, **kwargs: Any) -> Any:
        return await self._record("event.delete", args, kwargs)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        raise NotImplementedError(f"unsupported event method: {name}")


@dataclass(frozen=True, slots=True)
class DispatchResult:
    matched: bool
    handler: Callable[..., Any] | None = None
    event: FakeTelegramEvent | None = None
    pattern_match: re.Match[str] | None = None
    effects: tuple[RecordedEffect, ...] = ()


def _match_builder_pattern(builder: Any, text: str) -> re.Match[str] | None:
    """Use the NewMessage builder pattern callable without private Telethon state."""
    pattern = getattr(builder, "pattern", None)
    if pattern is None:
        raise TypeError(
            "Cannot deterministically match command: registered event builder has no pattern"
        )
    if callable(pattern):
        match = pattern(text)
    elif hasattr(pattern, "match"):
        match = pattern.match(text)
    elif isinstance(pattern, str):
        match = re.match(pattern, text)
    else:
        raise TypeError(
            "Cannot deterministically match command: unsupported event-builder pattern contract"
        )
    if match is None:
        return None
    if not hasattr(match, "group") or not hasattr(match, "groups"):
        raise TypeError(
            "Event-builder pattern did not return a regular-expression match object"
        )
    return match


async def emit_command(
    client: FakeTelegramClient,
    text: str,
    *,
    out: bool = True,
    chat_id: int | str = 10001,
    sender_id: int | str = 10002,
    id: int = 1,
) -> DispatchResult:
    """Dispatch text through the matching registered wrapper, never raw handlers."""
    for wrapper, builder in tuple(client.handlers):
        match = _match_builder_pattern(builder, text)
        if match is None:
            continue
        first_effect = len(client._recorder.effects)
        event = FakeTelegramEvent(
            text, client=client, pattern_match=match, out=out,
            chat_id=chat_id, sender_id=sender_id, id=id,
        )
        # Deliberately call the registered wrapper from add_event_handler.
        # The real registry wrapper alone decides whether to install its capability proxy.
        await wrapper(event)
        effects = tuple(client._recorder.effects[first_effect:])
        return DispatchResult(
            matched=True, handler=wrapper, event=event,
            pattern_match=match, effects=effects,
        )
    return DispatchResult(matched=False)
