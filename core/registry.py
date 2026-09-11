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
from core.errors import CommandError
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
    """Return conservative command-name fingerprints for collision detection.

    Existing plugins encode command names in their regex. We intentionally only
    fingerprint the command token, not arbitrary argument regex, to avoid false
    positives while still catching ``.block`` vs ``.block ...`` and grouped
    commands such as ``(block|unblock)``.
    """
    names: list[str] = []
    escaped_prefix = re.escape(config.PREFIX)
    prefix_match = re.search(rf"(?:\^)?{escaped_prefix}", pattern)
    if prefix_match:
        remainder = pattern[prefix_match.end():]
        remainder = remainder.lstrip()
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
    """Register one outgoing command with deterministic ownership.

    Registration fails before mutating the client when the same pattern or
    command token is already owned. This prevents silent duplicate commands.
    """
    if not pattern or not callable(handler):
        raise CommandRegistrationError("pattern and callable handler are required")

    names = _command_names(pattern, aliases)
    collisions: list[str] = []
    if pattern in COMMANDS:
        collisions.append(f"pattern {pattern!r}")
    collisions.extend(
        f"command {name!r}" for name in names if name in _COMMAND_OWNERS
    )
    if collisions:
        existing_ids = {
            _COMMAND_OWNERS[name]
            for name in names
            if name in _COMMAND_OWNERS
        }
        if pattern in COMMANDS:
            existing_ids.add(str(COMMANDS[pattern].get("registration_id", "unknown")))
        owners = sorted(
            {
                _REGISTRATIONS[item].owner or "unknown"
                for item in existing_ids
                if item in _REGISTRATIONS
            }
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
        except CommandError as exc:
            elapsed = time.perf_counter() - start_time
            logger.warning(
                "Command failed correlation=%s command=%s error=%s",
                correlation_id,
                pattern,
                exc.message,
            )
            await event.edit(render(
                title="ERROR",
                rows=[exc.message],
                footer=f"{elapsed:.2f}s | {category} | {correlation_id}",
            ))
        except Exception:
            elapsed = time.perf_counter() - start_time
            logger.error(
                "Unhandled command failure correlation=%s command=%s",
                correlation_id,
                pattern,
                exc_info=True,
            )
            # Do not expose exception types, paths, provider responses or args
            # to Telegram. Detailed diagnostics stay in logs.
            await event.edit(render(
                title="COMMAND FAILED",
                rows=["An unexpected error occurred.", f"Reference: {correlation_id}"],
                footer=f"{elapsed:.2f}s | {category}",
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

    # Commit registry state only after all validation has succeeded.
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
