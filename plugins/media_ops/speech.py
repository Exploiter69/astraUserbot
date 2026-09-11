import re
import os
import uuid
from pathlib import Path
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.shell import run
from helpers.reply import get_text_and_media
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(tts|toaudio)(?:\s+(.*))?$"


async def setup(client):
    register_cmd(client, PATTERN, handle_speech, "media_ops", "Neural TTS and Audio extraction.")


async def handle_speech(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2)
    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_file = cache_dir / f"speech_{uuid.uuid4().hex}.ogg"
    in_file = None

    try:
        if cmd == "tts":
            if not arg:
                raise CommandError("Provide text for TTS.")
            parts = arg.split("|")
            text = parts[0].strip()
            voice = parts[1].strip() if len(parts) > 1 else "en-US-ChristopherNeural"
            await event.edit(render("NEURAL TTS", [f"Voice: {voice}", "Generating..."]))
            rc, out, err = await run(["edge-tts", "--voice", voice, "--text", text, "--write-media", str(out_file)], timeout=60)
            if rc != 0:
                raise CommandError(f"TTS failed: {err[-300:]}")
        elif cmd == "toaudio":
            _, media = await get_text_and_media(event)
            if not media:
                raise CommandError("Reply to a video.")
            await event.edit(render("FFMPEG AUDIO", ["Extracting..."]))
            in_file = await event.client.download_media(media, file=cache_dir)
            if not in_file:
                raise CommandError("Failed to download media.")
            rc, out, err = await run(["ffmpeg", "-y", "-i", str(in_file), "-q:a", "0", "-map", "a", str(out_file)], timeout=120)
            if rc != 0:
                raise CommandError(f"Extraction failed: {err[-100:]}")

        await event.client.send_file(event.chat_id, file=out_file, voice_note=True, reply_to=event.reply_to_msg_id)
        await event.delete()
    finally:
        if in_file and os.path.exists(in_file):
            os.remove(in_file)
        out_file.unlink(missing_ok=True)
