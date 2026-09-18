"""Defensive URL, IDN and public reputation commands for Phase 10."""

from __future__ import annotations

import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render

plugin_name = "plugins.intelligence.security_intel"
plugin_version = "1.0.0"
plugin_api_version = 1
plugin_description = "Bounded defensive URL, IDN and public reputation analysis."
capabilities = ("network.request",)
critical = False

PATTERN = rf"^{re.escape(config.PREFIX)}(secrisk|idn|reputation)(?:\s+(.*))?$"


def _service():
    context = get_application_context()
    if context is None:
        raise CommandError("Runtime context is unavailable")
    return context.get("security_intel")


async def setup(client):
    register_cmd(
        client,
        PATTERN,
        handle,
        "intelligence",
        "Defensive URL risk, IDN/homoglyph and public reputation analysis.",
    )


async def handle(event):
    command = event.pattern_match.group(1).lower()
    target = (event.pattern_match.group(2) or "").strip()
    service = _service()
    if not target and command == "secrisk":
        reply = await event.get_reply_message()
        text = getattr(reply, "raw_text", "") if reply is not None else ""
        result = await service.assess_text(text)
        if not result["assessments"]:
            raise CommandError("Usage: .secrisk <url> or reply to a message containing a URL.")
        rows = [f"URLs analyzed: {len(result['assessments'])}"]
        for assessment in result["assessments"]:
            rows.extend([
                f"{assessment.target[:150]}",
                f"  Risk: {assessment.level} ({assessment.score}/100)",
                *[f"  · {signal[:170]}" for signal in assessment.signals[:5]],
            ])
        rows = rows[:18]
        rows.append("Defensive signal only; risk is not proof of maliciousness.")
        await event.edit(render("SECURITY // MESSAGE RISK", rows, footer="security | secrisk | bounded | public-only"))
        return
    if not target:
        raise CommandError(f"Usage: .{command} <url|domain|hash>")

    if command == "secrisk":
        try:
            result = await service.assess_url(target)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        rows = [
            f"Target: {result.target[:180]}",
            f"Risk: {result.level} ({result.score}/100)",
            *[f"· {signal[:180]}" for signal in result.signals[:10]],
            f"IDN ASCII: {result.idn.ascii[:180]}",
            f"Scripts: {', '.join(result.idn.scripts) or 'none'}",
        ]
        title = "SECURITY // URL RISK"
    elif command == "idn":
        try:
            result = service.analyze_idn(target)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        rows = [
            f"Input: {result.input[:180]}",
            f"ASCII: {result.ascii[:180]}",
            f"Unicode: {result.unicode[:180]}",
            f"Scripts: {', '.join(result.scripts) or 'none'}",
            f"Mixed script: {'YES' if result.mixed_script else 'NO'}",
            f"Punycode: {'YES' if result.punycode else 'NO'}",
            *[f"· {item[:180]}" for item in result.visual_similarity[:6]],
        ]
        title = "SECURITY // IDN"
    else:
        try:
            result = await service.inspect(target)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        rows = [f"Target: {target[:180]}"]
        if result["kind"] == "hash":
            rep = result["reputation"]
            rows += [
                f"Provider: {rep.get('provider', '—')}",
                f"Status: {rep.get('status', 'UNKNOWN')}",
                f"Signature: {rep.get('signature', '—')[:120]}",
                f"First seen: {rep.get('first_seen', '—')[:40]}",
            ]
        elif result["kind"] == "url":
            assessment = result["assessment"]
            rep = result["reputation"]
            rows += [
                f"Risk: {assessment.level} ({assessment.score}/100)",
                f"URLhaus: {rep.get('status', 'UNKNOWN')}",
                *[f"· {signal[:180]}" for signal in assessment.signals[:7]],
            ]
        else:
            idn = result["idn"]
            rows += [
                f"ASCII: {idn.ascii[:180]}",
                f"Mixed script: {'YES' if idn.mixed_script else 'NO'}",
                f"Punycode: {'YES' if idn.punycode else 'NO'}",
            ]
        title = "SECURITY // REPUTATION"

    rows = rows[:20]
    rows.append("Defensive signal only; similarity/risk is not proof of maliciousness.")
    await event.edit(render(title, rows, footer=f"security | {command} | bounded | public-only"))


