from __future__ import annotations

import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from core.services.telegram_sync import TelegramIncrementalSync
from helpers.hud import render

PATTERN = rf"^{re.escape(config.PREFIX)}tgsync(?:\s+(.*))?$"


def _ctx():
    context = get_application_context()
    if context is None:
        raise CommandError("Runtime context is unavailable")
    return context


async def handle(event):
    ctx = _ctx()
    raw = (event.pattern_match.group(1) or "").strip()
    parts = raw.split()
    if parts:
        target = parts[0]
        try:
            limit = int(parts[1]) if len(parts) > 1 else 100
        except ValueError as exc:
            raise CommandError("Usage: .tgsync [peer] [limit]") from exc
    else:
        reply = await event.get_reply_message()
        target = reply.chat if reply is not None and getattr(reply, "chat", None) is not None else event.chat_id
        limit = 100

    limit = max(1, min(limit, 100))
    telegram = ctx.get("telegram")
    storage = ctx.get("storage")
    if telegram is None or storage is None:
        raise CommandError("Telegram synchronization services are unavailable")

    sync = TelegramIncrementalSync(telegram, storage, max_batch=100)
    result = await sync.sync(target, limit=limit)
    cursor = await sync.cursor(target)
    rows = [
        f"Peer          {result.peer_key}",
        f"Fetched       {result.fetched}",
        f"Cursor        {result.last_message_id if result.last_message_id is not None else 'NONE'}",
        f"State         {result.state}",
        f"Gap detected  {'YES' if result.gap_detected else 'NO'}",
    ]
    if cursor is not None:
        rows.append(f"Last sync     {cursor.last_synced_at:.0f}")
    rows += ["", "BOUNDED · RESUMABLE · OBSERVATION SYNC"]
    await event.edit(render("TELEGRAM // INCREMENTAL SYNC", rows, footer="system_ops | tgsync | bounded state"))


async def setup(client):
    register_cmd(client, PATTERN, handle, "system_ops", "Run bounded resumable Telegram message synchronization from the durable cursor.")
