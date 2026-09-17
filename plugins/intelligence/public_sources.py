"""Phase 8 public-source intelligence commands."""

from __future__ import annotations

import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render

PATTERN = rf"^{re.escape(config.PREFIX)}(tgintel|userintel|domainintel|ct|linkintel|gitintel)(?:\s+(.*))?$"


def _service():
    context = get_application_context()
    if context is None:
        raise CommandError("Runtime context is unavailable")
    return context.get("public_intel")


async def setup(client):
    register_cmd(client, PATTERN, handle, "intelligence", "Bounded public-source intelligence collection with evidence and provenance.")


async def handle(event):
    command = event.pattern_match.group(1).lower()
    argument = (event.pattern_match.group(2) or "").strip()
    if not argument:
        raise CommandError(f"Usage: .{command} <target>")
    service = _service()
    try:
        if command == "tgintel":
            result = await service.telegram_intel(argument)
        elif command == "userintel":
            result = await service.username_pivot(argument)
        elif command == "domainintel":
            result = await service.domain_intel(argument)
        elif command == "ct":
            result = await service.certificate_transparency(argument)
        elif command == "linkintel":
            result = await service.link_intel(argument)
        elif command == "gitintel":
            result = await service.git_intel(argument)
        else:
            raise CommandError("Unknown intelligence command.")
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    rows = [str(row)[:500] for row in result.get("rows", [])]
    rows = rows[:32] or ["No public observations were produced."]
    await event.edit(render("INTELLIGENCE // PUBLIC SOURCES", rows, footer=f"intelligence | {command} | evidence-backed | public-only"))
