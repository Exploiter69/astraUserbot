"""Phase 9 media intelligence and durable investigation case commands."""
from __future__ import annotations

import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render

CASE_PATTERN = rf"^{re.escape(config.PREFIX)}case\s+(new|list|show|graph|add|event|timeline|report|close)(?:\s+(.*))?$"
MEDIA_PATTERN = rf"^{re.escape(config.PREFIX)}mediaintel$"
SIMILAR_PATTERN = rf"^{re.escape(config.PREFIX)}mediasim\s+([0-9a-fA-F]{{16}})$"


def _context():
    context = get_application_context()
    if context is None:
        raise CommandError("Runtime context is unavailable")
    return context


async def setup(client):
    register_cmd(client, MEDIA_PATTERN, handle_media, "intelligence", "Analyze replied or attached media with bounded hashing, OCR, frames and speech evidence.")
    register_cmd(client, SIMILAR_PATTERN, handle_similar, "intelligence", "Find bounded perceptual-media candidates by pHash.")
    register_cmd(client, CASE_PATTERN, handle_case, "intelligence", "Manage durable investigation cases, graphs and timelines.")


async def _resolve_media(event):
    """Resolve media from the command message first, then its replied message.

    Some Telethon event wrappers do not expose a reliable ``is_reply`` flag even
    when the command message has a reply-to header, so prefer direct reply
    resolution and fall back to the command message itself. A few lightweight
    event test doubles expose ``get_reply_message`` as an unbound callable;
    support that shape without changing normal Telethon behavior.
    """
    if getattr(event, "media", None):
        return event.media
    try:
        reply = await event.get_reply_message()
    except TypeError:
        raw_get_reply = getattr(type(event), "get_reply_message", None)
        if raw_get_reply is None:
            reply = None
        else:
            try:
                reply = await raw_get_reply()
            except Exception:
                reply = None
    except Exception:
        reply = None
    return getattr(reply, "media", None) if reply is not None else None


async def handle_media(event):
    media = await _resolve_media(event)
    if not media:
        raise CommandError("Reply to an image, audio, video, or document to analyze it.")
    context = _context()
    service = context.get("media_intel")
    media_service = context.get("media")
    workspace = await media_service.create_workspace("media_command")
    try:
        downloaded = await media_service.download_telegram_media(event.client.download_media, media, workspace=workspace)
        if not downloaded:
            raise CommandError("Failed to download media.")
        result = await service.analyze_file(downloaded)
    finally:
        await media_service.cleanup(workspace)
    rows = [f"SHA-256: `{result['sha256']}`", f"Size: {result['size_bytes']:,} bytes", f"Type: `{result['media_type']}`"]
    if result.get("phash"):
        rows.append(f"pHash: `{result['phash']}`")
    if result.get("dhash"):
        rows.append(f"dHash: `{result['dhash']}`")
    if result.get("ahash"):
        rows.append(f"aHash: `{result['ahash']}`")
    if result.get("frames_sampled"):
        rows.append(f"Frames sampled: {result['frames_sampled']}")
    if result.get("ioc_count"):
        rows.append(f"IOCs extracted: {result['ioc_count']}")
    if result.get("ocr_text"):
        rows.append("OCR: " + str(result["ocr_text"])[:1500])
    if result.get("transcript"):
        rows.append("Transcript: " + str(result["transcript"])[:1500])
    await event.edit(render("MEDIA INTELLIGENCE", rows, footer="intelligence | mediaintel | evidence-backed | bounded"))


async def handle_similar(event):
    service = _context().get("media_intel")
    matches = await service.similar(event.pattern_match.group(1))
    rows = [f"`{item['phash']}` · distance={item['distance']}" for item in matches]
    await event.edit(render("PERCEPTUAL MEDIA MATCHES", rows or ["No bounded candidates within distance threshold."], footer="intelligence | mediasim | derived"))


async def handle_case(event):
    action = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip()
    context = _context()
    cases = context.get("cases")
    if action == "new":
        if not arg:
            raise CommandError("Usage: `.case new <title>`")
        case_id = await cases.create(arg)
        await event.edit(render("CASE CREATED", [f"ID: `{case_id}`", f"Title: {arg[:200]}", "Status: OPEN"], footer="intelligence | case"))
        return
    if action == "list":
        rows = await cases.list()
        lines = [f"`{item['case_id'][:12]}` · {item['status']} · {item['title'][:120]}" for item in rows]
        await event.edit(render("CASES", lines or ["No cases."], footer="intelligence | cases"))
        return
    if not arg:
        raise CommandError(f"Usage: `.case {action} <case-id> ...`")
    parts = arg.split(None, 2)
    case_id = parts[0]
    case = await cases.get(case_id)
    if not case:
        raise CommandError("Case not found.")
    if action == "show":
        entities = await cases.entities(case_id)
        timeline = await cases.timeline(case_id, limit=25)
        lines = [f"ID: `{case_id}`", f"Title: {case['title']}", f"Status: {case['status']}", f"Entities: {len(entities)}", f"Timeline entries: {len(timeline)}"]
        await event.edit(render("CASE", lines, footer="intelligence | case | durable"))
    elif action == "graph":
        entities = await cases.entities(case_id, limit=25)
        intel = context.get("intelgraph")
        lines = []
        for item in entities:
            neighbors = await intel.neighbors(item["entity_id"], limit=8)
            label = item["display_value"] or item["canonical_value"]
            lines.append(f"{item['entity_type']} {label[:100]}")
            lines.extend(f"  · {edge['direction']} {edge['relationship_type']} → {edge['related_entity_id'][:12]}" for edge in neighbors[:8])
        await event.edit(render("CASE GRAPH", lines[:50] or ["No entities attached."], footer="intelligence | case | graph | bounded"))
    elif action == "add":
        if len(parts) < 2:
            raise CommandError("Usage: `.case add <case-id> <intel-target>`")
        matches = await context.get("intelgraph").resolve_target(parts[1])
        if len(matches) != 1:
            raise CommandError("Target must resolve to exactly one IntelGraph entity.")
        await cases.add_entity(case_id, matches[0]["entity_id"])
        await event.edit(render("CASE ENTITY", [f"Attached: `{matches[0]['entity_id']}`", f"Type: {matches[0]['entity_type']}"], footer="intelligence | case"))
    elif action == "event":
        if len(parts) < 3:
            raise CommandError("Usage: `.case event <case-id> <kind> <description>`")
        await cases.add_timeline(case_id, parts[1], parts[2])
        await event.edit(render("CASE TIMELINE", ["Event recorded."], footer="intelligence | case"))
    elif action == "timeline":
        timeline = await cases.timeline(case_id)
        lines = [f"{item['kind']} · {item['description'][:180]}" for item in timeline]
        await event.edit(render("CASE TIMELINE", lines or ["No timeline entries."], footer="intelligence | case | timeline"))
    elif action == "report":
        report = await cases.report(case_id)
        await event.edit(report)
    elif action == "close":
        if case["status"] == "CLOSED":
            await event.edit(render("CASE", ["Case is already closed."], footer="intelligence | case"))
            return
        await cases.close_case(case_id)
        await event.edit(render("CASE CLOSED", [f"ID: `{case_id}`"], footer="intelligence | case"))
    else:
        raise CommandError("Unknown case action.")
