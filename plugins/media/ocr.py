import re
import shutil
import logging

from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.reply import get_text_and_media
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
        description="Extract text from a replied image using isolated Tesseract OCR."
    )

async def handle_ocr(event):
    _, media = await get_text_and_media(event)
    if not media:
        raise CommandError("Please reply to an image to perform OCR.")

    context = get_application_context()
    if context is None:
        raise CommandError("Required runtime services are unavailable.")
    media_service = context.get("media")
    workspace_service = context.get("workspace")

    await event.edit(render(title="OCR", rows=["Downloading image..."], footer="media | ocr"))

    workspace = await workspace_service.create("ocr")
    file_path = workspace.path / "input.jpg"
    downloaded_path = await event.client.download_media(media, file=file_path)
    if not downloaded_path:
        await workspace_service.cleanup(workspace)
        raise CommandError("Failed to download media.")

    try:
        await event.edit(render(title="OCR", rows=["Running isolated Tesseract (bounded)..."], footer="media | ocr"))
        result = await media_service.run_isolated(
            ["tesseract", "/workspace/input.jpg", "stdout", "-l", "eng"],
            workspace=workspace,
            timeout=60,
            max_output_bytes=512 * 1024,
        )
        if result.returncode != 0:
            raise CommandError("Tesseract failed: " + (result.stderr.strip() or "Unknown error"))

        text = result.stdout.strip() if result.stdout.strip() else "No text detected in image."
        await event.edit(render(
            title="OCR RESULT",
            rows=["---"] + text.splitlines(),
            footer="media | ocr"
        ))
    finally:
        await workspace_service.cleanup(workspace)
