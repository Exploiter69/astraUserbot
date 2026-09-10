import re
import os
import uuid
import shutil
from pathlib import Path
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.shell import run
from helpers.concurrency import CPU_BOUND
from helpers.reply import get_text_and_media
from helpers.progress import ProgressCallback
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}mediaflow(?:\s+(compress|extract|square))?$"

async def setup(client):
    if not shutil.which("ffmpeg"):
        return
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_mediaflow,
        category="advanced",
        description="Advanced media transformation. Usage: .mediaflow [compress|extract|square]"
    )

async def handle_mediaflow(event):
    mode = (event.pattern_match.group(1) or "compress").lower()
    _, media = await get_text_and_media(event)
    
    if not media:
        raise CommandError("Please reply to a video, audio, or GIF file.")

    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    uid = uuid.uuid4().hex
    in_file = await event.client.download_media(media, file=cache_dir)
    
    if not in_file or not os.path.exists(in_file):
        raise CommandError("Failed to download media file.")

    await event.edit(render(
        title="MEDIAFLOW",
        rows=[f"Mode: {mode.upper()}", "Processing via FFmpeg..."],
        footer="advanced | mediaflow"
    ))

    out_ext = "mp3" if mode == "extract" else "mp4"
    out_file = cache_dir / f"flow_{uid}.{out_ext}"

    if mode == "compress":
        ffmpeg_cmd = f'ffmpeg -y -i "{in_file}" -c:v libx264 -crf 26 -preset fast -c:a aac -b:a 128k "{out_file}"'
    elif mode == "extract":
        ffmpeg_cmd = f'ffmpeg -y -i "{in_file}" -vn -c:a libmp3lame -b:a 320k "{out_file}"'
    elif mode == "square":
        ffmpeg_cmd = f'ffmpeg -y -i "{in_file}" -vf "crop=w=\'min(in_w,in_h)\':h=\'min(in_w,in_h)\'" -c:v libx264 -crf 23 -c:a copy "{out_file}"'
    else:
        if os.path.exists(in_file):
            os.remove(in_file)
        raise CommandError("Invalid mode. Use: compress, extract, or square")

    try:
        async with CPU_BOUND:
            rc, out, err = await run(ffmpeg_cmd, timeout=300)

        if rc != 0 or not out_file.exists():
            raise CommandError(f"FFmpeg pipeline failed: {err[-300:]}")

        up_prog = ProgressCallback(event, f"Uploading ({mode})")
        await event.client.send_file(
            event.chat_id,
            file=out_file,
            progress_callback=up_prog,
            reply_to=event.reply_to_msg_id
        )
        await event.delete()
    finally:
        if in_file and os.path.exists(in_file):
            os.remove(in_file)
        if out_file.exists():
            out_file.unlink()
