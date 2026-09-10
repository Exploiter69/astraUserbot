import re
import shlex
from pathlib import Path
from telethon import events
from core.registry import register_cmd
from helpers.hud import render
from helpers.shell import run
from helpers.concurrency import CPU_BOUND
from core.errors import CommandError
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}ff(?:\s+(.*))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_ffmpeg,
        category="media",
        description="FFmpeg and FFprobe media processing workbench."
    )

async def handle_ffmpeg(event):
    raw_args = event.pattern_match.group(1) or ""
    reply = await event.get_reply_message()
    
    if not reply or not reply.media:
        raise CommandError("Please reply to an audio, video, or photo to process with FFmpeg.")

    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    await event.edit(render("FFMPEG", ["Downloading source media..."]))
    downloaded_path = await reply.download_media(file=cache_dir)
    if not downloaded_path:
        raise CommandError("Failed to download media file.")
        
    downloaded = Path(downloaded_path)
    out_file = cache_dir / f"ff_out_{downloaded.stem}{downloaded.suffix}"

    try:
        user_args = shlex.split(raw_args) if raw_args.strip() else ["-c", "copy"]
    except ValueError as e:
        raise CommandError(f"Malformed quotes in FFmpeg arguments: {e}")

    await event.edit(render("FFMPEG", ["Processing media stream with FFmpeg..."]))
    
    argv = ["ffmpeg", "-y", "-i", str(downloaded), *user_args, str(out_file)]
    
    async with CPU_BOUND:
        rc, out, err = await run(argv, timeout=300)

    if rc != 0 or not out_file.exists():
        if downloaded.exists():
            downloaded.unlink(missing_ok=True)
        raise CommandError(f"FFmpeg error:\n{err[-300:]}")

    await event.edit(render("FFMPEG", ["Uploading processed output..."]))
    await event.client.send_file(
        event.chat_id,
        file=str(out_file),
        caption=f"Processed with: `ffmpeg {' '.join(user_args)}`",
        reply_to=reply.id
    )

    downloaded.unlink(missing_ok=True)
    out_file.unlink(missing_ok=True)
    await event.delete()
