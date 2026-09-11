"""Central command registration and invocation routing.

The public ``register_cmd`` function intentionally remains compatible with the
legacy plugin API. Internally, every registration receives an owner, a stable
handle, collision checks, permission metadata and a correlation id per invoke.
"""

from __future__ import annotations

import inspect
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from telethon import events

from config import config
from core.errors import AstraError, CommandError, as_astra_error, user_message
from core.plugins.manager import PluginManager
from helpers.hud import render

logger = logging.getLogger("astra.registry")


class CommandRegistrationError(ValueError):
    """Raised when a command registration would be ambiguous or invalid."""


@dataclass(frozen=True, slots=True)
class CommandRegistration:
    """Metadata and removal handle for one registered command."""

    registration_id: str
    pattern: str
    handler: Callable[..., Any]
    category: str
    description: str
    aliases: tuple[str, ...] = ()
    permission: str = "owner"
    owner: str | None = None
    event_builder: Any = field(default=None, compare=False, repr=False)
    wrapper: Callable[..., Any] = field(default=lambda event: None, compare=False, repr=False)

    def unregister(self, client: Any) -> None:
        """Remove this registration from the Telethon client and registry."""
        client.remove_event_handler(self.wrapper, self.event_builder)
        COMMANDS.pop(self.pattern, None)
        _REGISTRATIONS.pop(self.registration_id, None)
        for command in _command_names(self.pattern, self.aliases):
            if _COMMAND_OWNERS.get(command) == self.registration_id:
                _COMMAND_OWNERS.pop(command, None)


# Kept public for existing help/introspection plugins.
COMMANDS: Dict[str, Dict[str, Any]] = {}
_REGISTRATIONS: Dict[str, CommandRegistration] = {}
_COMMAND_OWNERS: Dict[str, str] = {}


def _command_names(pattern: str, aliases: Optional[Iterable[str]] = None) -> tuple[str, ...]:
    """Return conservative command-name fingerprints for collision detection."""
    names: list[str] = []
    escaped_prefix = re.escape(config.PREFIX)
    prefix_match = re.search(rf"(?:\^)?{escaped_prefix}", pattern)
    if prefix_match:
        remainder = pattern[prefix_match.end():].lstrip()
        group = re.match(r"\(([^()]+)\)", remainder)
        if group:
            names.extend(part.strip() for part in group.group(1).split("|") if part.strip())
        else:
            literal = re.match(r"([A-Za-z0-9_:-]+)", remainder)
            if literal:
                names.append(literal.group(1))

    for alias in aliases or ():
        alias = alias.strip().lstrip(config.PREFIX)
        if alias:
            names.append(alias)
    return tuple(sorted(set(name.lower() for name in names)))


def _new_correlation_id() -> str:
    return uuid.uuid4().hex[:12]


def register_cmd(
    client: Any,
    pattern: str,
    handler: Callable,
    category: str = "system",
    description: str = "No description provided.",
    aliases: Optional[List[str]] = None,
    permission: str = "owner",
) -> CommandRegistration:
    """Register one outgoing command with deterministic ownership."""
    if not pattern or not callable(handler):
        raise CommandRegistrationError("pattern and callable handler are required")

    names = _command_names(pattern, aliases)
    collisions: list[str] = []
    if pattern in COMMANDS:
        collisions.append(f"pattern {pattern!r}")
    collisions.extend(f"command {name!r}" for name in names if name in _COMMAND_OWNERS)
    if collisions:
        existing_ids = {_COMMAND_OWNERS[name] for name in names if name in _COMMAND_OWNERS}
        if pattern in COMMANDS:
            existing_ids.add(str(COMMANDS[pattern].get("registration_id", "unknown")))
        owners = sorted(
            {_REGISTRATIONS[item].owner or "unknown" for item in existing_ids if item in _REGISTRATIONS}
        )
        owner_text = ", ".join(owners) if owners else "existing registration"
        raise CommandRegistrationError(
            f"Command collision ({', '.join(collisions)}) with {owner_text}"
        )

    owner = PluginManager.current_plugin()
    registration_id = uuid.uuid4().hex
    event_builder = events.NewMessage(outgoing=True, pattern=pattern)

    async def wrapper(event: Any) -> None:
        if not event.out:
            return
        correlation_id = _new_correlation_id()
        start_time = time.perf_counter()
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            error = as_astra_error(
                exc,
                operation="command",
                component=owner or category,
                correlation_id=correlation_id,
            )
            if isinstance(exc, AstraError):
                logger.warning(
                    "Command failure correlation=%s command=%s code=%s error=%s",
                    correlation_id,
                    pattern,
                    error.code,
                    error.message,
                )
            else:
                logger.error(
                    "Unhandled command failure correlation=%s command=%s code=%s",
                    correlation_id,
                    pattern,
                    error.code,
                    exc_info=True,
                )
            if isinstance(exc, CommandError):
                rows = [user_message(error)]
                title = "ERROR"
            else:
                rows = ["An unexpected error occurred.", f"Reference: {correlation_id}"]
                title = "COMMAND FAILED"
            await event.edit(render(
                title=title,
                rows=rows,
                footer=f"{elapsed:.2f}s | {category}" + (
                    f" | {correlation_id}" if isinstance(exc, CommandError) else ""
                ),
            ))

    registration = CommandRegistration(
        registration_id=registration_id,
        pattern=pattern,
        handler=handler,
        category=category,
        description=description,
        aliases=tuple(aliases or ()),
        permission=permission,
        owner=owner,
        event_builder=event_builder,
        wrapper=wrapper,
    )

    client.add_event_handler(wrapper, event_builder)
    COMMANDS[pattern] = {
        "registration_id": registration_id,
        "handler": handler.__name__,
        "category": category,
        "description": description,
        "aliases": list(registration.aliases),
        "permission": permission,
        "owner": owner,
    }
    _REGISTRATIONS[registration_id] = registration
    for name in names:
        _COMMAND_OWNERS[name] = registration_id

    manager = getattr(client, "plugin_manager", None)
    if manager is not None:
        manager.register_ownership(registration_id)
    else:
        logger.debug("Command %s registered without attached plugin manager", pattern)

    logger.debug(
        "Registered command %s owner=%s id=%s",
        pattern,
        owner or "legacy",
        registration_id,
    )
    return registration


def get_registration(registration_id: str) -> CommandRegistration:
    return _REGISTRATIONS[registration_id]


def list_registrations() -> list[CommandRegistration]:
    return sorted(_REGISTRATIONS.values(), key=lambda item: item.pattern)


def clear_registrations(client: Any) -> None:
    """Remove every command registration; primarily for controlled shutdown/tests."""
    for registration in list(_REGISTRATIONS.values()):
        registration.unregister(client)
