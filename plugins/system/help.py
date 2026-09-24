"""Canonical command discovery and operator help."""

from __future__ import annotations

import re

from config import config
from core.registry import command_metadata, find_registrations, list_registrations, register_cmd
from helpers.hud import render

HELP_PATTERN = rf"^{re.escape(config.PREFIX)}help(?:\s+(.*))?$"
COMMAND_PATTERN = rf"^{re.escape(config.PREFIX)}command\s+(search|describe|examples|category|aliases|permissions|source)(?:\s+(.*))?$"


def _names(registration) -> list[str]:
    return list(command_metadata(registration)["names"])


def _display(registration) -> str:
    meta = command_metadata(registration)
    names = [config.PREFIX + name for name in meta["names"]]
    return " / ".join(names)


def _rows_for_all() -> list[str]:
    registrations = list_registrations()
    rows = [
        "Astra Command Manual · live registry",
        f"Registrations: {len(registrations)}",
        "Use .help <command> or .command describe <command>.",
        "---",
    ]
    grouped: dict[str, list[str]] = {}
    for registration in registrations:
        meta = command_metadata(registration)
        grouped.setdefault(meta["category"], []).append(_display(registration))
    for category in sorted(grouped):
        rows.append(f"◈ {category.upper()}")
        rows.extend(f"  {item}" for item in sorted(grouped[category], key=str.lower))
    return rows


def _resolve(query: str):
    matches = find_registrations(query)
    return matches[0] if matches else None


def _rows_for_one(registration) -> list[str]:
    meta = command_metadata(registration)
    rows = [
        _display(registration),
        "---",
        meta["description"] or "No description provided.",
        f"Category: {meta['category']}",
        f"Plugin: {meta['plugin'] or 'legacy'}",
        f"Permission: {meta['permission']}",
        f"Operation: {meta['operation_class']}",
        f"Network: {'yes' if meta['network'] else 'no'}",
        f"Durable job: {'yes' if meta['durable_job'] else 'no'}",
        f"Destructive: {'yes' if meta['destructive'] else 'no'}",
        f"Confirmation: {'yes' if meta['confirmation_required'] else 'no'}",
        f"Compatibility: {meta['compatibility']}",
        f"Usage: {meta['usage']}",
        f"Examples: {' | '.join(meta['examples'])}",
    ]
    if meta["required_capabilities"]:
        rows.append(f"Capabilities: {', '.join(meta['required_capabilities'])}")
    if meta["source_ref"]:
        rows.append(f"Source: {meta['source_ref']}")
    return rows


async def setup(client):
    register_cmd(
        client,
        HELP_PATTERN,
        handle_help,
        category="system",
        description="Show live command discovery and canonical command metadata.",
        examples=[f"{config.PREFIX}help", f"{config.PREFIX}help status"],
    )
    register_cmd(
        client,
        COMMAND_PATTERN,
        handle_command,
        category="system",
        description="Search and inspect the live command contract.",
        examples=[
            f"{config.PREFIX}command search intel",
            f"{config.PREFIX}command describe status",
            f"{config.PREFIX}command examples search",
        ],
    )


async def handle_help(event):
    query = (event.pattern_match.group(1) or "").strip()
    if not query:
        await event.edit(render("COMMAND DECK", _rows_for_all()[:120], footer="system | live registry"))
        return
    registration = _resolve(query)
    if registration is None:
        await event.edit(render("HELP", [f"Unknown command: {query}", f"Try {config.PREFIX}command search <query>"], footer="system | help"))
        return
    await event.edit(render("COMMAND", _rows_for_one(registration)[:24], footer="system | contract"))


async def handle_command(event):
    action = (event.pattern_match.group(1) or "").lower()
    query = (event.pattern_match.group(2) or "").strip()
    if action == "search":
        if not query:
            raise ValueError(f"Usage: {config.PREFIX}command search <query>")
        matches = find_registrations(query)
        rows = [f"{_display(item)} · {command_metadata(item)['description'][:100]}" for item in matches]
        await event.edit(render("COMMAND SEARCH", rows or ["No matching commands."], footer="system | bounded | max 25"))
        return
    if not query:
        raise ValueError(f"Usage: {config.PREFIX}command {action} <command>")
    registration = _resolve(query)
    if registration is None:
        await event.edit(render("COMMAND", [f"Unknown command: {query}"], footer="system | registry"))
        return
    meta = command_metadata(registration)
    if action == "describe":
        rows = _rows_for_one(registration)
    elif action == "examples":
        rows = [str(item) for item in meta["examples"]]
    elif action == "category":
        category = query.lower()
        matches = [item for item in list_registrations() if command_metadata(item)["category"].lower() == category]
        rows = [_display(item) for item in matches] or [f"No commands in category: {category}"]
    elif action == "aliases":
        rows = [config.PREFIX + str(item) for item in meta["aliases"]] or ["No aliases."]
    elif action == "permissions":
        rows = [f"Permission: {meta['permission']}", f"Capabilities: {', '.join(meta['required_capabilities']) or 'none'}"]
    elif action == "source":
        rows = [meta["source_ref"] or f"Plugin: {meta['plugin'] or 'legacy'}"]
    else:
        rows = ["Unsupported discovery action."]
    await event.edit(render(f"COMMAND // {action.upper()}", rows[:32], footer="system | registry"))


