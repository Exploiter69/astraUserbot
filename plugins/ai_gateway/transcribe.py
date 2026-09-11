import os
import re
import uuid
from pathlib import Path

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render
from helpers.reply import get_text_and_media

PATTERN = rf"^{re.escape(config.PREFIX)}transcribe$"


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_transcribe,
        category="ai",
        description="Transcribe voice notes/audio via the configured AI provider.",
    )


async def handle_transcribe(event):
    _, media = await get_text_and_media(event)
    if not media:
        raise CommandError("Please reply to an audio file or voice note.")

    context = get_application_context()
    if context is None:
        raise CommandError("AI service is unavailable.")
    service = context.get("ai")

    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / f"whisper_{uuid.uuid4().hex}.ogg"

    await event.edit(render(
        title="WHISPER",
        rows=["Downloading audio media..."],
        footer="ai | transcribe",
    ))
    downloaded_path = await event.client.download_media(media, file=file_path)
    if not downloaded_path:
        raise CommandError("Failed to download audio media.")

    await event.edit(render(
        title="WHISPER",
        rows=[f"Transcribing via {service.provider_name}..."],
        footer="ai | transcribe",
    ))

    try:
        response = await service.transcribe(downloaded_path)
        text = response.text or "[No speech detected in audio]"
        await event.edit(render(
            title="TRANSCRIPTION",
            rows=["---"] + text.split("\n"),
            footer=f"ai | transcribe | {response.provider}",
        ))
    finally:
        try:
            if os.path.exists(downloaded_path):
                os.remove(downloaded_path)
        except OSError:
            pass
