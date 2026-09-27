"""Canonical command discovery and operator help."""

from __future__ import annotations

import re

from config import config
from core.errors import CommandError
from core.registry import (
    command_metadata,
    find_registrations,
    list_registrations,
    recent_registrations,
    register_cmd,
)
from helpers.hud import render

HELP_PATTERN = rf"^{re.escape(config.PREFIX)}help(?:\s+(.*))?$"
COMMAND_PATTERN = rf"^{re.escape(config.PREFIX)}command\s+(search|describe|examples|category|aliases|permissions|source|recent)(?:\s+(.*))?$"

# Gate-A discoverability contract marker.
HELP_DISCOVERY_MARKER = ".help <command-or-category>"


def _names(registration) -> list[str]:
    return list(command_metadata(registration)["names"])


def _display(registration) -> str:
    meta = command_metadata(registration)
    names = [config.PREFIX + name for name in meta["names"]]
    return " / ".join(names)


def _command_deck_rows(registrations) -> tuple[int, dict[str, list[str]]]:
    """Expand registrations into the concrete command names shown to operators."""
    grouped: dict[str, list[str]] = {}
    exposed = 0
    for registration in registrations:
        meta = command_metadata(registration)
        names = [f"{config.PREFIX}{name}" for name in meta["names"]]
        exposed += len(names)
        grouped.setdefault(meta["category"], []).extend(names)
    grouped = {
        category: sorted(dict.fromkeys(names), key=str.lower)
        for category, names in grouped.items()
    }
    return exposed, grouped


def _rows_for_all() -> list[str]:
    """Render every concrete command name, not merely every registration."""
    registrations = list_registrations()
    exposed, grouped = _command_deck_rows(registrations)
    rows = [
        "Astra Command Manual · live registry",
        f"Commands exposed: {exposed}  ·  registrations: {len(registrations)}",
        f"Use {HELP_DISCOVERY_MARKER}, .help <category> or {config.PREFIX}command describe <command>.",
        "---",
    ]
    for category in sorted(grouped):
        # Keep the command deck compact so the full inventory remains visible.
        # One category line can carry the same concrete-name inventory that the
        # old operator-facing deck exposed, while the discovery commands provide
        # detailed per-command metadata.
        rows.append(f"◈ {category.upper()}  {' '.join(grouped[category])}")
    return rows

def _resolve(query: str):
    matches = find_registrations(query)
    return matches[0] if matches else None


def _category_rows(category: str) -> list[str]:
    needle = category.strip().lower()
    registrations = [
        item
        for item in list_registrations()
        if command_metadata(item)["category"].lower() == needle
    ]
    return [_display(item) for item in registrations]


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
        f"Compatibility: {meta['compatibility']} · plugin v{meta['owner_version']}",
        f"Priority: {meta['priority']} · timeout: {meta['timeout_seconds']:.0f}s",
        f"Cancellation: {'yes' if meta['cancellation_supported'] else 'no'} · durable execution: {'yes' if meta['durable_execution_supported'] else 'no'}",
        f"Arguments: {meta['argument_schema'] or 'none'}",
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
        examples=[
            f"{config.PREFIX}help",
            f"{config.PREFIX}help status",
            f"{config.PREFIX}help intelligence",
        ],
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
            f"{config.PREFIX}command category intelligence",
        ],
    )


async def handle_help(event):
    query = (event.pattern_match.group(1) or "").strip()
    if not query:
        await event.edit(
            render("COMMAND DECK", _rows_for_all(), footer="system | live registry")
        )
        return
    category_rows = _category_rows(query)
    if category_rows:
        await event.edit(
            render(
                "COMMAND CATEGORY",
                [f"Category: {query}", "---", *category_rows[:80]],
                footer="system | category",
            )
        )
        return
    registration = _resolve(query)
    if registration is None:
        await event.edit(
            render(
                "HELP",
                [
                    f"Unknown command/category: {query}",
                    f"Try {config.PREFIX}command search <query>",
                ],
                footer="system | help",
            )
        )
        return
    await event.edit(
        render("COMMAND", _rows_for_one(registration)[:24], footer="system | contract")
    )


async def handle_command(event):
    action = (event.pattern_match.group(1) or "").lower()
    query = (event.pattern_match.group(2) or "").strip()
    if action == "recent":
        registrations = recent_registrations(10)
        rows = [_display(item) for item in registrations]
        await event.edit(
            render(
                "COMMAND // RECENT",
                rows or ["No recent command history."],
                footer="system | privacy-safe recent identities",
            )
        )
        return
    if action == "search":
        if not query:
            raise CommandError(f"Usage: {config.PREFIX}command search <query>")
        matches = find_registrations(query)
        rows = [
            f"{_display(item)} · {command_metadata(item)['description'][:100]}"
            for item in matches
        ]
        await event.edit(
            render(
                "COMMAND SEARCH",
                rows or ["No matching commands."],
                footer="system | bounded | max 25",
            )
        )
        return
    if action == "category":
        if not query:
            raise CommandError(f"Usage: {config.PREFIX}command category <name>")
        rows = _category_rows(query)
        await event.edit(
            render(
                "COMMAND // CATEGORY",
                [f"Category: {query}", "---", *rows[:80]]
                if rows
                else [f"No commands in category: {query}"],
                footer="system | registry",
            )
        )
        return
    if not query:
        raise CommandError(f"Usage: {config.PREFIX}command {action} <command>")
    registration = _resolve(query)
    if registration is None:
        await event.edit(
            render("COMMAND", [f"Unknown command: {query}"], footer="system | registry")
        )
        return
    meta = command_metadata(registration)
    if action == "describe":
        rows = _rows_for_one(registration)
    elif action == "examples":
        rows = [str(item) for item in meta["examples"]]
    elif action == "aliases":
        rows = [config.PREFIX + str(item) for item in meta["aliases"]] or [
            "No aliases."
        ]
    elif action == "permissions":
        rows = [
            f"Permission: {meta['permission']}",
            f"Capabilities: {', '.join(meta['required_capabilities']) or 'none'}",
        ]
    elif action == "source":
        rows = [meta["source_ref"] or f"Plugin: {meta['plugin'] or 'legacy'}"]
    else:
        rows = ["Unsupported discovery action."]
    await event.edit(
        render(f"COMMAND // {action.upper()}", rows[:32], footer="system | registry")
    )
