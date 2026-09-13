import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render
from helpers.reply import get_text_and_media

PATTERN = rf"^{re.escape(config.PREFIX)}transcribe$"

async def setup(client):
    register_cmd(client, pattern=PATTERN, handler=handle_transcribe, category="ai", description="Transcribe voice notes/audio via the configured AI provider.")

async def handle_transcribe(event):
    _, media = await get_text_and_media(event)
    if not media:
        raise CommandError("Please reply to an audio file or voice note.")
    mime = getattr(media, "mime_type", None)
    if mime and not (mime.startswith("audio/") or mime in {"application/ogg", "application/octet-stream"}):
        raise CommandError("Replied media is not an audio file or voice note.")

    context = get_application_context()
    if context is None:
        raise CommandError("AI service is unavailable.")
    service = context.get("ai")
    media_service = context.get("media")
    if service is None or media_service is None:
        raise CommandError("Required runtime services are unavailable.")

    await event.edit(render(title="WHISPER", rows=["Downloading audio media..."], footer="ai | transcribe"))
    workspace = await media_service.create_workspace("transcribe")
    try:
        downloaded_path = await media_service.download_telegram_media(
            event.client.download_media,
            media,
            workspace=workspace,
        )
        if not downloaded_path:
            raise CommandError("Failed to download audio media.")
        artifact = media_service.artifact(workspace, downloaded_path)
        if artifact.size_bytes > service.max_audio_bytes:
            raise CommandError("Audio exceeds the configured AI transcription size limit.")
        await event.edit(render(title="WHISPER", rows=[f"Transcribing via {service.provider_name}..."], footer="ai | transcribe"))
        response = await service.transcribe(artifact.path)
        text = response.text or "[No speech detected in audio]"
        await event.edit(render(title="TRANSCRIPTION", rows=["---"] + text.split("\n"), footer=f"ai | transcribe | {response.provider}"))
    finally:
        await media_service.cleanup(workspace)
