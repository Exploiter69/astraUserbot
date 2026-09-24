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
from collections import deque
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
    operation_class: str = "READ"
    required_capabilities: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    compatibility: str = "1.0"
    network: bool = False
    durable_job: bool = False
    destructive: bool = False
    confirmation_required: bool = False
    resource_class: str = "default"
    source_ref: str = ""
    usage: str = ""
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


COMMANDS: Dict[str, Dict[str, Any]] = {}
_REGISTRATIONS: Dict[str, CommandRegistration] = {}
_COMMAND_OWNERS: Dict[str, str] = {}
_RECENT_COMMANDS: deque[str] = deque(maxlen=50)


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
    operation_class: str | None = None,
    required_capabilities: Optional[List[str]] = None,
    examples: Optional[List[str]] = None,
    compatibility: str = "1.0",
    network: bool | None = None,
    durable_job: bool | None = None,
    destructive: bool | None = None,
    confirmation_required: bool | None = None,
    resource_class: str = "default",
    source_ref: str = "",
    usage: str = "",
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
        _RECENT_COMMANDS.append(registration_id)
        correlation_id = _new_correlation_id()
        start_time = time.perf_counter()
        metrics = None
        try:
            # Runtime import avoids a core.registry <-> core.context import cycle.
            from core.context import get_application_context
            context = get_application_context()
            if context is not None:
                metrics = context.get("metrics")
                metrics.increment("commands.total")
        except Exception:
            metrics = None
        try:
            if metrics is not None:
                with metrics.timer(f"command.{category}"):
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
            else:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            if metrics is not None:
                metrics.increment("commands.failed")
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

    primary_name = names[0] if names else "command"
    description_lower = description.lower()
    op_text = operation_class.upper() if operation_class else ""
    if not op_text:
        if any(token in primary_name for token in ("delete", "remove", "purge", "wipe", "clear")) or any(token in description_lower for token in ("delete", "purge", "wipe")):
            op_text = "DESTRUCTIVE"
        elif category in {"jobs", "job"} or any(token in primary_name for token in ("job", "task", "retry", "cancel")):
            op_text = "JOB"
        elif any(token in primary_name for token in ("send", "edit", "rename", "block", "unblock", "ban", "unban", "enable", "disable", "restart", "update", "close")):
            op_text = "MUTATION"
        elif any(token in description_lower for token in ("network", "http", "public-source", "telegram", "url", "remote", "provider")):
            op_text = "NETWORK"
        else:
            op_text = "READ"
    if op_text not in {"READ", "NETWORK", "MUTATION", "DESTRUCTIVE", "JOB"}:
        raise CommandRegistrationError(f"Unsupported operation class: {op_text}")
    if not compatibility or len(compatibility) > 32:
        raise CommandRegistrationError("Command compatibility metadata is invalid.")
    destructive_value = bool(destructive) if destructive is not None else op_text == "DESTRUCTIVE"
    confirmation_value = bool(confirmation_required) if confirmation_required is not None else destructive_value
    network_value = bool(network) if network is not None else op_text == "NETWORK"
    durable_value = bool(durable_job) if durable_job is not None else op_text == "JOB"
    example_values = tuple(examples or (f"{config.PREFIX}{primary_name}",))
    capability_values = tuple(required_capabilities or ())
    usage_value = usage or example_values[0]
    source_ref_value = source_ref or f"{getattr(handler, '__module__', 'unknown')}:{getattr(handler, '__name__', 'handler')}"

    registration = CommandRegistration(
        registration_id=registration_id,
        pattern=pattern,
        handler=handler,
        category=category,
        description=description,
        aliases=tuple(aliases or ()),
        permission=permission,
        owner=owner,
        operation_class=op_text,
        required_capabilities=capability_values,
        examples=example_values,
        compatibility=compatibility,
        network=network_value,
        durable_job=durable_value,
        destructive=destructive_value,
        confirmation_required=confirmation_value,
        resource_class=resource_class,
        source_ref=source_ref_value,
        usage=usage_value,
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
        "operation_class": op_text,
        "required_capabilities": list(capability_values),
        "examples": list(example_values),
        "compatibility": compatibility,
        "network": network_value,
        "durable_job": durable_value,
        "destructive": destructive_value,
        "confirmation_required": confirmation_value,
        "resource_class": resource_class,
        "source_ref": source_ref_value,
        "usage": usage_value,
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

def command_metadata(registration: CommandRegistration) -> dict[str, Any]:
    """Return the stable, JSON-safe command contract."""
    return {
        "registration_id": registration.registration_id,
        "pattern": registration.pattern,
        "names": list(_command_names(registration.pattern, registration.aliases)),
        "aliases": list(registration.aliases),
        "plugin": registration.owner,
        "category": registration.category,
        "description": registration.description,
        "usage": registration.usage,
        "examples": list(registration.examples),
        "permission": registration.permission,
        "operation_class": registration.operation_class,
        "required_capabilities": list(registration.required_capabilities),
        "compatibility": registration.compatibility,
        "network": registration.network,
        "durable_job": registration.durable_job,
        "destructive": registration.destructive,
        "confirmation_required": registration.confirmation_required,
        "resource_class": registration.resource_class,
        "source_ref": registration.source_ref,
    }

def find_registrations(query: str) -> list[CommandRegistration]:
    """Bounded deterministic command discovery over the live registry."""
    needle = str(query).strip().lstrip(config.PREFIX).lower()
    if not needle:
        return list_registrations()
    scored: list[tuple[int, CommandRegistration]] = []
    for registration in list_registrations():
        names = _command_names(registration.pattern, registration.aliases)
        haystack = " ".join((registration.category, registration.description, registration.owner or "", *names)).lower()
        if needle in names:
            score = 100
        elif any(name.startswith(needle) for name in names):
            score = 80
        elif needle in haystack:
            score = 50
        else:
            continue
        scored.append((score, registration))
    return [item[1] for item in sorted(scored, key=lambda pair: (-pair[0], pair[1].pattern))[:25]]

def registry_snapshot() -> list[dict[str, Any]]:
    return [command_metadata(item) for item in list_registrations()]


def recent_registrations(limit: int = 10) -> list[CommandRegistration]:
    """Return privacy-safe recent command identities; arguments are never stored."""
    bounded = max(1, min(int(limit), 25))
    seen: set[str] = set()
    result: list[CommandRegistration] = []
    for registration_id in reversed(_RECENT_COMMANDS):
        if registration_id in seen:
            continue
        seen.add(registration_id)
        registration = _REGISTRATIONS.get(registration_id)
        if registration is not None:
            result.append(registration)
        if len(result) >= bounded:
            break
    return result
