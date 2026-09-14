"""Normalize selected Telethon updates into bounded local event envelopes."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable

from telethon import events

logger = logging.getLogger("astra.telegram_events")

EventSink = Callable[["TelegramEvent"], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class TelegramEvent:
    """Bounded normalized event; never contains the raw Telethon update."""

    event_id: str
    event_type: str
    observed_at: float
    source_peer: str | None
    message_id: int | None
    entity_id: int | None
    payload: dict[str, Any]
    schema_version: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class TelegramEventCollector:
    """Collect supported Telegram updates and fan out normalized event envelopes.

    The collector is deliberately transport-adjacent: it observes Telethon updates,
    strips them down to bounded metadata, and forwards the normalized event to sinks.
    Durable storage belongs to the following event-journal gate.
    """

    MAX_SINKS = 32
    MAX_TEXT_BYTES = 4096

    def __init__(self, client: Any) -> None:
        self.client = client
        self._sinks: list[EventSink] = []
        self._handlers: list[tuple[Any, Any]] = []
        self._started = False

    def add_sink(self, sink: EventSink) -> None:
        if not callable(sink):
            raise TypeError("event sink must be callable")
        if sink in self._sinks:
            return
        if len(self._sinks) >= self.MAX_SINKS:
            raise RuntimeError("event sink limit reached")
        self._sinks.append(sink)

    def remove_sink(self, sink: EventSink) -> None:
        if sink in self._sinks:
            self._sinks.remove(sink)

    async def start(self) -> None:
        if self._started:
            return
        registrations = (
            (self._handle_new_message, events.NewMessage()),
            (self._handle_message_edit, events.MessageEdited()),
            (self._handle_message_delete, events.MessageDeleted()),
            (self._handle_reaction, events.MessageReactionUpdated()),
            (self._handle_chat_action, events.ChatAction()),
        )
        for callback, builder in registrations:
            self.client.add_event_handler(callback, builder)
            self._handlers.append((callback, builder))
        self._started = True
        logger.info("Telegram event collector started handlers=%d", len(self._handlers))

    async def close(self) -> None:
        if not self._started:
            return
        for callback, builder in reversed(self._handlers):
            self.client.remove_event_handler(callback, builder)
        self._handlers.clear()
        self._started = False
        self._sinks.clear()
        logger.info("Telegram event collector stopped")

    async def _emit(self, event_type: str, event: Any, *, payload: dict[str, Any], message_id: int | None = None) -> None:
        normalized = TelegramEvent(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            observed_at=time.time(),
            source_peer=self._peer_key(event),
            message_id=message_id,
            entity_id=self._entity_id(event),
            payload=self._bound_payload(payload),
        )
        sinks = tuple(self._sinks)
        for sink in sinks:
            try:
                result = sink(normalized)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram event sink failed event_type=%s", event_type)

    async def _handle_new_message(self, event: Any) -> None:
        message = getattr(event, "message", None)
        await self._emit("MESSAGE_NEW", event, payload=self._message_payload(message), message_id=self._message_id(message))

    async def _handle_message_edit(self, event: Any) -> None:
        message = getattr(event, "message", None)
        await self._emit("MESSAGE_EDIT", event, payload=self._message_payload(message), message_id=self._message_id(message))

    async def _handle_message_delete(self, event: Any) -> None:
        ids = getattr(event, "deleted_ids", None) or ()
        for message_id in tuple(ids)[:100]:
            await self._emit("MESSAGE_DELETE", event, payload={"deleted": True}, message_id=int(message_id))

    async def _handle_reaction(self, event: Any) -> None:
        message = getattr(event, "message", None)
        await self._emit("REACTION_CHANGED", event, payload={"message": self._message_id(message)}, message_id=self._message_id(message))

    async def _handle_chat_action(self, event: Any) -> None:
        action = getattr(event, "action_message", None)
        await self._emit(
            "CHAT_MEMBER_CHANGED",
            event,
            payload={"action": type(action).__name__ if action is not None else type(event).__name__},
        )

    @staticmethod
    def _message_id(message: Any) -> int | None:
        value = getattr(message, "id", None)
        return int(value) if isinstance(value, int) else None

    @staticmethod
    def _entity_id(event: Any) -> int | None:
        for name in ("sender_id", "user_id", "chat_id"):
            value = getattr(event, name, None)
            if isinstance(value, int):
                return value
        message = getattr(event, "message", None)
        value = getattr(message, "sender_id", None)
        return int(value) if isinstance(value, int) else None

    @staticmethod
    def _peer_key(event: Any) -> str | None:
        value = getattr(event, "chat_id", None)
        if value is None:
            value = getattr(event, "peer_id", None)
        if value is None:
            return None
        return str(value)

    @classmethod
    def _message_payload(cls, message: Any) -> dict[str, Any]:
        if message is None:
            return {}
        text = getattr(message, "raw_text", None)
        if isinstance(text, str):
            text = text[: cls.MAX_TEXT_BYTES]
        return {
            "text": text,
            "has_media": bool(getattr(message, "media", None)),
            "out": bool(getattr(message, "out", False)),
            "reply_to": getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None),
        }

    @classmethod
    def _bound_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """Keep collector output JSON-friendly and bounded."""
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                result[str(key)] = value
            elif isinstance(value, (list, tuple)):
                result[str(key)] = [str(item)[:256] for item in value[:100]]
            else:
                result[str(key)] = str(value)[:256]
        return result
