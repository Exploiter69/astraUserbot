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
    if media_service is None or workspace_service is None:
        raise CommandError("Required runtime services are unavailable.")

    await event.edit(render(title="OCR", rows=["Downloading image..."], footer="media | ocr"))
    workspace = await media_service.create_workspace("ocr")
    try:
        downloaded_path = await media_service.download_telegram_media(
            event.client.download_media,
            media,
            workspace=workspace,
        )
        if not downloaded_path:
            raise CommandError("Failed to download media.")
        artifact = media_service.artifact(workspace, downloaded_path)
        await event.edit(render(title="OCR", rows=["Running isolated Tesseract (bounded)..."], footer="media | ocr"))
        result = await media_service.run_isolated(
            ["tesseract", "/workspace/" + artifact.path.relative_to(workspace.path).as_posix(), "stdout", "-l", "eng"],
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
        await media_service.cleanup(workspace)
