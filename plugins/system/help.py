"""Registry-canonical command help.

The live command registry is the source of truth. Help intentionally does not
maintain a second hand-written usage database, so removed or changed command
contracts cannot become stale documentation.
"""

from __future__ import annotations

import re

from config import config
from core.registry import list_registrations, register_cmd
from helpers.hud import render

PATTERN = rf"^{re.escape(config.PREFIX)}help(?:\s+(.*))?$"

_CATEGORY_LABELS = {
    "security": "SECURITY",
    "stealth": "SECURITY",
    "crypto": "SECURITY",
    "backup": "STORAGE",
    "storage": "STORAGE",
    "network_osint": "OSINT",
    "advanced": "OSINT",
    "ai": "AI / MEDIA",
    "media": "AI / MEDIA",
    "media_ops": "AI / MEDIA",
    "system": "SYSTEM",
    "system_ops": "SYSTEM",
    "admin_ops": "SYSTEM",
    "fun": "FUN",
}


def _command_names(registration) -> tuple[str, ...]:
    names: list[str] = []
    prefix = re.escape(config.PREFIX)
    match = re.search(rf"{prefix}(?:\\()?([A-Za-z0-9_:-]+)", registration.pattern)
    if match:
        names.append(match.group(1).lower())
    names.extend(alias.lstrip(config.PREFIX).lower() for alias in registration.aliases)
    return tuple(dict.fromkeys(name for name in names if name))


def _display_command(registration) -> str:
    names = _command_names(registration)
    if not names:
        return registration.pattern
    primary = names[0]
    aliases = [name for name in names[1:] if name != primary]
    suffix = f" (aliases: {', '.join(config.PREFIX + a for a in aliases)})" if aliases else ""
    return f"{config.PREFIX}{primary}{suffix}"


def _rows_for_all() -> list[str]:
    registrations = list_registrations()
    grouped: dict[str, list[str]] = {}
    for registration in registrations:
        label = _CATEGORY_LABELS.get(registration.category, registration.category.upper())
        grouped.setdefault(label, []).append(_display_command(registration))
    rows = [f"Registered commands: {len(registrations)}", "---"]
    for label in sorted(grouped):
        rows.append(f"[{label}]")
        rows.extend(sorted(grouped[label], key=str.lower))
    return rows


def _find(query: str):
    needle = query.strip().lstrip(config.PREFIX).lower()
    if not needle:
        return None
    for registration in list_registrations():
        if needle in _command_names(registration):
            return registration
    for registration in list_registrations():
        if needle in registration.description.lower():
            return registration
    return None


def _rows_for_one(registration) -> list[str]:
    rows = [
        _display_command(registration),
        "---",
        registration.description or "No description provided.",
        f"Category: {registration.category}",
        f"Permission: {registration.permission}",
        f"Owner: {registration.owner or 'legacy'}",
        f"Pattern: {registration.pattern}",
    ]
    if registration.aliases:
        rows.append("Aliases: " + ", ".join(registration.aliases))
    return rows


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_help,
        category="system",
        description="Show the live command registry and canonical command metadata.",
    )


async def handle_help(event):
    query = (event.pattern_match.group(1) or "").strip()
    if query:
        registration = _find(query)
        if registration is None:
            await event.edit(
                render(
                    "HELP",
                    [f"Unknown command: {query}", "Use .help to list registered commands."],
                    footer="system | help",
                )
            )
            return
        rows = _rows_for_one(registration)
    else:
        rows = _rows_for_all()
    await event.edit(render("HELP", rows[:120], footer="system | help | registry"))
