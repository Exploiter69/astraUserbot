"""Owner-facing commands for the durable Telegram Archive Engine."""

from __future__ import annotations

import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render
from helpers.ux import job_buttons

PATTERN = rf"^{re.escape(config.PREFIX)}archive(?:\s+(.*))?$"
MAX_DISPLAY_RESULTS = 10


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_archive,
        category="archive",
        description="Queue bounded Telegram history/media archives and search the local archive.",
        permission="owner",
    )


def _limit(value: str | None, default: int = 100) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CommandError("Archive limit must be an integer.") from exc
    if not 1 <= parsed <= 500:
        raise CommandError("Archive limit must be between 1 and 500.")
    return parsed


def _current_peer(event) -> str:
    peer = getattr(event, "chat_id", None)
    if peer is None:
        raise CommandError("Archive commands require a Telegram chat context.")
    return str(peer)


async def handle_archive(event):
    context = get_application_context()
    if context is None:
        raise CommandError("Application context is unavailable.")
    archive = context.get("telegram_archive")
    args = (event.pattern_match.group(1) or "").strip()
    if not args:
        raise CommandError(
            "Usage: `.archive chat [limit]`, `.archive channel [limit]`, `.archive since <message_id> [limit]`, `.archive media [limit]`, or `.archive search <query>`"
        )

    parts = args.split()
    mode = parts[0].lower()

    if mode == "search":
        query = args[len(parts[0]):].strip()
        if not query:
            raise CommandError("Archive search requires a query.")
        results = await archive.search_archive(query, limit=MAX_DISPLAY_RESULTS)
        if not results:
            await event.edit(render("ARCHIVE SEARCH", ["No archived messages matched."], footer="archive | search"))
            return
        rows = [f"{item['title']}: {item['snippet']}" for item in results]
        await event.edit(render("ARCHIVE SEARCH", rows, footer=f"archive | {len(results)} result(s)"))
        return

    if mode not in {"chat", "channel", "since", "media"}:
        raise CommandError("Unknown archive mode.")

    peer = _current_peer(event)
    min_message_id = 0
    include_media = mode == "media"
    limit = 100

    if mode in {"chat", "channel", "media"}:
        if len(parts) > 2:
            raise CommandError(f"Usage: `.archive {mode} [limit]` in the current chat.")
        if len(parts) == 2:
            limit = _limit(parts[1])
    else:
        if len(parts) not in {2, 3}:
            raise CommandError("Usage: `.archive since <message_id> [limit]` in the current chat.")
        try:
            min_message_id = int(parts[1])
        except ValueError as exc:
            raise CommandError("Archive message ID must be an integer.") from exc
        if min_message_id < 0:
            raise CommandError("Archive message ID cannot be negative.")
        if len(parts) == 3:
            limit = _limit(parts[2])

    await event.edit(render("ARCHIVE", [f"Queueing {mode} archive for `{peer}`..."], footer="archive | durable job"))
    job = await archive.enqueue(
        peer,
        limit=limit,
        min_message_id=min_message_id,
        include_media=include_media,
        owner="owner",
    )
    await event.edit(
        render(
            "ARCHIVE QUEUED",
            [
                f"Job: `{job.id[:12]}`",
                f"Peer: `{peer}`",
                f"Limit: {limit}",
                f"Media: {'enabled' if include_media else 'metadata only'}",
                "Work is resumable and rate-governed.",
                f"Inspect with `{config.PREFIX}job {job.id[:12]}`.",
            ],
            footer="archive | JobEngine",
        ),
        buttons=job_buttons(job.id, state=str(job.state)),
    )
