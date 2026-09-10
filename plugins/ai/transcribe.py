import re
import os
import uuid
from pathlib import Path
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.reply import get_text_and_media
from plugins.ai.groq_client import transcribe_audio
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}transcribe$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_transcribe,
        category="ai",
        description="Transcribe voice notes/audio via Cloud Whisper API."
    )

async def handle_transcribe(event):
    _, media = await get_text_and_media(event)
    
    if not media:
        raise CommandError("Please reply to an audio file or voice note.")
        
    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / f"whisper_{uuid.uuid4().hex}.ogg"
    
    await event.edit(render(
        title="WHISPER",
        rows=["Downloading audio media..."],
        footer="ai | transcribe"
    ))
    
    downloaded_path = await event.client.download_media(media, file=file_path)
    
    if not downloaded_path:
        raise CommandError("Failed to download audio media.")
        
    await event.edit(render(
        title="WHISPER",
        rows=["Transcribing in cloud..."],
        footer="ai | transcribe"
    ))
    
    try:
        text = await transcribe_audio(downloaded_path)
        if not text:
            text = "[No speech detected in audio]"
            
        rows = ["---"] + text.split('\n')
        
        await event.edit(render(
            title="TRANSCRIPTION",
            rows=rows,
            footer="ai | transcribe"
        ))
    finally:
        # Guarantee cleanup of temporary audio files to keep data/cache minimal
        if os.path.exists(downloaded_path):
            os.remove(downloaded_path)
