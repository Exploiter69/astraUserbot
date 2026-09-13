import re
import shutil

from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.reply import get_text_and_media
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(tts|toaudio)(?:\s+(.*))?$"


async def setup(client):
    if not shutil.which("edge-tts"):
        return
    register_cmd(client, PATTERN, handle_speech, "media_ops", "Neural TTS and Audio extraction.")


async def handle_speech(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2)

    context = get_application_context()
    if context is None:
        raise CommandError("Media service is unavailable.")
    service = context.get("media")
    workspace = await service.create_workspace("speech")

    try:
        output_name = "output.ogg"
        if cmd == "tts":
            if not arg:
                raise CommandError("Provide text for TTS.")
            parts = arg.split("|")
            text = parts[0].strip()
            voice = parts[1].strip() if len(parts) > 1 else "en-US-ChristopherNeural"
            if not text:
                raise CommandError("TTS text cannot be empty.")
            if len(text) > 3000:
                raise CommandError("TTS text is too long (max 3000 characters).")
            if not voice or len(voice) > 128:
                raise CommandError("Invalid TTS voice.")
            await event.edit(render("NEURAL TTS", [f"Voice: {voice}", "Generating..."]))
            artifact = await service.run_tts(
                workspace=workspace,
                text=text,
                voice=voice,
                output_name=output_name,
                timeout=60,
            )
        elif cmd == "toaudio":
            _, media = await get_text_and_media(event)
            if not media:
                raise CommandError("Reply to a video with an audio stream.")
            mime_type = getattr(media, "mime_type", "") or ""
            if not (getattr(media, "video", False) or mime_type.startswith("video/")):
                raise CommandError("The replied media is not a video.")
            service.validate_telegram_media(media)
            await event.edit(render("FFMPEG AUDIO", ["Extracting..."]))
            in_file = await event.client.download_media(
                media,
                file=workspace.path,
                progress_callback=service.telegram_download_progress(),
            )
            if not in_file:
                raise CommandError("Failed to download media.")
            await service.run_ffmpeg(
                workspace=workspace,
                input_path=in_file,
                output_name=output_name,
                options=["-q:a", "0", "-map", "a"],
                timeout=120,
            )
            artifact = service.artifact(workspace, output_name)
        else:
            raise CommandError("Unsupported speech operation.")

        await event.client.send_file(event.chat_id, file=artifact.path, voice_note=True, reply_to=event.reply_to_msg_id)
        await event.delete()
    finally:
        await service.cleanup(workspace)
