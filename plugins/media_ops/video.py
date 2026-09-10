import re
import os
import uuid
from pathlib import Path
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.shell import run
from helpers.concurrency import CPU_BOUND
from helpers.reply import get_text_and_media
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(round|ss|compress|reverse)(?:\s+(.*))?$"

async def setup(client):
    register_cmd(client, PATTERN, handle_video, "media_ops", "Advanced video manipulation (FFmpeg).")

async def handle_video(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2)
    _, media = await get_text_and_media(event)
    if not media: raise CommandError("Reply to a video/GIF.")
    
    cache_dir = Path("data/cache")
    uid = uuid.uuid4().hex
    in_file = await event.client.download_media(media, file=cache_dir)
    out_file = cache_dir / f"vid_{uid}.mp4"
    
    await event.edit(render("VIDEO OPS", [f"Operation: {cmd.upper()}", "Processing (CPU Bound)..."]))
    
    ffmpeg_cmd = ""
    if cmd == "round":
        ffmpeg_cmd = f"ffmpeg -y -i '{in_file}' -vf 'crop=w=\'min(in_w,in_h)\':h=\'min(in_w,in_h)\',scale=512:512' -c:v libx264 -crf 24 -an '{out_file}'"
    elif cmd == "ss":
        sec = arg or "00:00:01"
        out_file = cache_dir / f"ss_{uid}.jpg"
        ffmpeg_cmd = f"ffmpeg -y -ss {sec} -i '{in_file}' -vframes 1 -q:v 2 '{out_file}'"
    elif cmd == "compress":
        ffmpeg_cmd = f"ffmpeg -y -i '{in_file}' -c:v libx264 -crf 28 -preset fast -c:a aac -b:a 128k '{out_file}'"
    elif cmd == "reverse":
        ffmpeg_cmd = f"ffmpeg -y -i '{in_file}' -vf reverse -af areverse '{out_file}'"

    async with CPU_BOUND:
        rc, out, err = await run(ffmpeg_cmd, timeout=300)
        
    try:
        if rc != 0: raise CommandError(f"FFmpeg failed: {err[-300:]}")
        is_vn = (cmd == "round")
        await event.client.send_file(event.chat_id, file=out_file, video_note=is_vn, reply_to=event.reply_to_msg_id)
        await event.delete()
    finally:
        if os.path.exists(in_file): os.remove(in_file)
        if out_file.exists(): out_file.unlink()
