"""Operator surface for the local IntelGraph foundation."""
from __future__ import annotations

import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render


async def setup(client):
    prefix = re.escape(config.PREFIX)
    register_cmd(
        client,
        rf"^{prefix}intel\s+(graph|timeline)(?:\s+(\S+))?(?:\s+(\d+))?$",
        handle_intel,
        "intel",
        "Query bounded IntelGraph relationships or evidence timelines.",
    )


async def shutdown(_client):
    return None


async def handle_intel(event):
    context = get_application_context()
    if context is None:
        raise CommandError("IntelGraph is unavailable.")
    graph = context.get("intelgraph")
    action = event.pattern_match.group(1).lower()
    target = event.pattern_match.group(2)
    page_text = event.pattern_match.group(3)
    if not target:
        raise CommandError(f"Usage: {config.PREFIX}intel {action} <target> [page]")
    page = max(1, int(page_text or "1"))
    if action == "graph":
        await _handle_graph(event, graph, target, page)
    else:
        await _handle_timeline(event, graph, target, page)


async def _handle_graph(event, graph, target: str, page: int) -> None:
    per_page = 12
    result = await graph.graph(target, limit=per_page, offset=(page - 1) * per_page)
    if result is None:
        await event.edit(render("INTELGRAPH", [f"No entity matches `{_escape(target)}`."], footer="intel | graph"))
        return
    if result.get("ambiguous"):
        rows = [
            f"`{item['entity_type']}` · `{_escape(str(item['canonical_value']))}`"
            for item in result["candidates"]
        ]
        await event.edit(render("INTELGRAPH AMBIGUOUS", rows[:20], footer="intel | graph | refine target"))
        return

    root = result["root"]
    rows = [
        f"ROOT `{root['entity_type']}` · `{_escape(str(root['display_value'] or root['canonical_value']))}`",
        f"Edges: `{result['total_edges']}` · Page: `{page}`",
    ]
    for edge in result["edges"]:
        other_id = edge["to_id"] if edge["from_id"] == root["entity_id"] else edge["from_id"]
        other = next((node for node in result["nodes"] if node["entity_id"] == other_id), None)
        if other is None:
            continue
        value = other["display_value"] or other["canonical_value"]
        rows.append(
            f"{edge['relationship_type']} → `{_escape(str(value))}` "
            f"[{edge['evidence_state']} {float(edge['confidence']):.2f}]"
        )
    if result["has_more"]:
        rows.append(f"Next: `{config.PREFIX}intel graph {target} {page + 1}`")
    await event.edit(render("INTELGRAPH", rows[:18], footer="intel | graph | evidence-backed"))


async def _handle_timeline(event, graph, target: str, page: int) -> None:
    matches = await graph.resolve_target(target)
    if not matches:
        await event.edit(render("INTEL TIMELINE", [f"No entity matches `{_escape(target)}`."], footer="intel | timeline"))
        return
    if len(matches) > 1:
        rows = [
            f"`{item['entity_type']}` · `{_escape(str(item['canonical_value']))}`"
            for item in matches[:20]
        ]
        await event.edit(render("INTEL TIMELINE AMBIGUOUS", rows, footer="intel | timeline | refine target"))
        return

    per_page = 10
    entries = await graph.timeline(matches[0]["entity_id"], limit=min(100, page * per_page))
    start = (page - 1) * per_page
    page_entries = entries[start : start + per_page]
    if not page_entries:
        await event.edit(render("INTEL TIMELINE", ["No timeline entries on this page."], footer="intel | timeline"))
        return
    rows = []
    for item in page_entries:
        state = item["evidence_state"]
        confidence = float(item["confidence"])
        rows.append(f"{item['kind']} · {state} {confidence:.2f} · {float(item['timestamp']):.0f}")
    if start + len(page_entries) < len(entries):
        rows.append(f"Next: `{config.PREFIX}intel timeline {target} {page + 1}`")
    await event.edit(render("INTEL TIMELINE", rows[:14], footer="intel | timeline | bounded"))


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
