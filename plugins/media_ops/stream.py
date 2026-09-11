import re
from pathlib import Path
from telethon import events
from core.registry import register_cmd
from helpers.hud import render
from helpers.shell import run
from helpers.concurrency import IO_BOUND
from core.errors import CommandError
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}rip(?:\s+(audio|video|doc|best))?(?:\s+(https?://\S+))?$"


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_rip,
        category="media_ops",
        description="Universal stream and media extractor powered by yt-dlp.",
    )


async def handle_rip(event):
    mode = event.pattern_match.group(1) or "video"
    url = event.pattern_match.group(2)
    if not url:
        reply = await event.get_reply_message()
        if reply and reply.raw_text:
            match = re.search(r"https?://\S+", reply.raw_text)
            if match:
                url = match.group(0)
    if not url:
        raise CommandError(f"Usage: `{config.PREFIX}rip <audio|video|doc|best> <URL>`")

    from core.context import get_application_context
    context = get_application_context()
    workspace_service = context.get("workspace") if context else None
    workspace = await workspace_service.create("rip") if workspace_service else None
    cache_dir = workspace.path if workspace else Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(cache_dir / "%(title).50s.%(ext)s")

    await event.edit(render("RIP // STREAM", [f"Mode: `{mode}`", f"Target: `{url}`", "Extracting stream..."]))
    if mode == "audio":
        argv = ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", out_tmpl, "--no-playlist", "--max-filesize", "1900M", url]
    elif mode == "doc":
        argv = ["yt-dlp", "-f", "best", "-o", out_tmpl, "--no-playlist", "--max-filesize", "1900M", url]
    else:
        argv = ["yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "-o", out_tmpl, "--no-playlist", "--max-filesize", "1900M", url]

    try:
        async with IO_BOUND:
            rc, out, err = await run(argv, timeout=600)
        if rc != 0:
            raise CommandError(f"yt-dlp extraction failed:\n{err[-300:]}")

        extracted_files = sorted(cache_dir.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
        target_file = next((f for f in extracted_files if f.is_file() and not f.name.endswith(".tmp")), None)
        if not target_file or not target_file.exists():
            raise CommandError("Extracted file could not be located on disk.")

        await event.edit(render("RIP // UPLOADING", [f"File: `{target_file.name}`", "Uploading to chat..."]))
        await event.client.send_file(event.chat_id, file=str(target_file), caption=f"Extracted: `{target_file.name}`", reply_to=event.id)
        await event.delete()
    finally:
        if workspace_service and workspace:
            await workspace_service.cleanup(workspace)
