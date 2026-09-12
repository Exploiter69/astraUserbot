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
    "security": "SECURITY & FORENSICS", "stealth": "SECURITY & FORENSICS", "crypto": "SECURITY & FORENSICS",
    "backup": "CLOUD & STORAGE", "storage": "CLOUD & STORAGE",
    "network_osint": "OSINT & RECON", "advanced": "OSINT & RECON",
    "ai": "AI & MEDIA FLOW", "media": "AI & MEDIA FLOW", "media_ops": "AI & MEDIA FLOW",
    "system": "SYSTEM OPS", "system_ops": "SYSTEM OPS", "admin_ops": "SYSTEM OPS", "fun": "SYSTEM OPS",
    "utilities": "UTILITIES",
}


def _command_names(registration) -> tuple[str, ...]:
    """Extract command names from the command expression at pattern start."""
    names: list[str] = []
    prefix = re.escape(config.PREFIX)
    if registration.pattern.startswith(f"^{prefix}"):
        command_expr = registration.pattern[len(f"^{prefix}"):]
        if command_expr.startswith("("):
            end = command_expr.find(")")
            if end > 0:
                group = command_expr[1:end]
                if re.fullmatch(r"[A-Za-z0-9_:-]+(?:\|[A-Za-z0-9_:-]+)*", group):
                    names.extend(group.split("|"))
        else:
            match = re.match(r"[A-Za-z0-9_:-]+", command_expr)
            if match:
                names.append(match.group(0))
    names.extend(alias.lstrip(config.PREFIX).lower() for alias in registration.aliases)
    return tuple(dict.fromkeys(name.lower() for name in names if name))


def _display_command(registration) -> str:
    names = _command_names(registration)
    if not names:
        return "Unknown command expression"
    primary, *aliases = names
    suffix = f"  ·  aliases: {', '.join(config.PREFIX + name for name in aliases)}" if aliases else ""
    return f"{config.PREFIX}{primary}{suffix}"


def _pack_commands(commands: list[str], width: int = 44) -> list[str]:
    rows: list[str] = []
    current = ""
    for command in commands:
        candidate = command if not current else f"{current}  {command}"
        if current and len(candidate) > width:
            rows.append(current)
            current = command
        else:
            current = candidate
    if current:
        rows.append(current)
    return rows


def _rows_for_all() -> list[str]:
    registrations = list_registrations()
    grouped: dict[str, list[str]] = {}
    command_count = 0
    for registration in registrations:
        label = _CATEGORY_LABELS.get(registration.category, registration.category.upper())
        names = _command_names(registration)
        command_count += len(names)
        grouped.setdefault(label, []).extend(config.PREFIX + name for name in names)
    rows = [
        "Astra Command Manual · live registry",
        f"Commands exposed: {command_count}  ·  registrations: {len(registrations)}",
        "Use .help <command> for a focused operator card.",
        "---",
    ]
    for label in sorted(grouped):
        rows.append(f"◈ {label}")
        rows.extend(f"  {packed}" for packed in _pack_commands(sorted(dict.fromkeys(grouped[label]), key=str.lower)))
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
    names = _command_names(registration)
    rows = [
        _display_command(registration),
        "---",
        registration.description or "No description provided.",
        f"Category: {registration.category}",
        f"Permission: {registration.permission}",
        f"Owner: {registration.owner or 'legacy'}",
        f"Registered names: {', '.join(config.PREFIX + name for name in names) if names else 'unavailable'}",
    ]
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
            await event.edit(render("HELP", [f"Unknown command: {query}", "Use .help to list registered commands."], footer="system | help"))
            return
        rows = _rows_for_one(registration)
    else:
        rows = _rows_for_all()
    await event.edit(render("COMMAND DECK", rows[:120], footer="system | registry | .help <command>"))
