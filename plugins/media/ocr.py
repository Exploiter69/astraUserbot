import re
import os
import uuid
import shutil
import logging
from pathlib import Path
from telethon import events
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.reply import get_text_and_media
from helpers.shell import run
from helpers.concurrency import CPU_BOUND
from config import config

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}ocr$"

async def setup(client):
    if not shutil.which("tesseract"):
        logger.warning("tesseract binary missing. OCR plugin disabled.")
        return
        
    register_cmd(
        client, 
        pattern=PATTERN, 
        handler=handle_ocr, 
        category="media", 
        description="Extract text from a replied image using Tesseract OCR."
    )

async def handle_ocr(event):
    _, media = await get_text_and_media(event)
    if not media:
        raise CommandError("Please reply to an image to perform OCR.")
        
    await event.edit(render(title="OCR", rows=["Downloading image..."], footer="media | ocr"))
    
    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / f"ocr_{uuid.uuid4().hex}.jpg"
    
    downloaded_path = await event.client.download_media(media, file=file_path)
    if not downloaded_path:
        raise CommandError("Failed to download media.")
    
    await event.edit(render(title="OCR", rows=["Running Tesseract (CPU Bound)..."], footer="media | ocr"))
    
    try:
        # Constrain heavy local OCR processing to the CPU_BOUND semaphore
        async with CPU_BOUND:
            rc, out, err = await run(["tesseract", str(downloaded_path), "stdout", "-l", "eng"], timeout=60)
        
        if rc != 0:
            raise CommandError(f"Tesseract failed: {err.strip()}")
            
        text = out.strip() if out.strip() else "No text detected in image."
        
        await event.edit(render(
            title="OCR RESULT",
            rows=["---"] + text.split('\n'),
            footer="media | ocr"
        ))
    finally:
        if os.path.exists(downloaded_path):
            os.remove(downloaded_path)
