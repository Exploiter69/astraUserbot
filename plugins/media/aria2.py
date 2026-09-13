import re
import shutil
import logging
from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.progress import ProgressCallback
from config import config

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}aria(?:\s+(.*))?$"


async def setup(client):
    if not shutil.which("aria2c"):
        logger.warning("aria2c missing. Aria2 plugin disabled.")
        return
    register_cmd(client, pattern=PATTERN, handler=handle_aria, category="media", description="Download a file via aria2c. Usage: .aria <url>")


async def handle_aria(event):
    url = (event.pattern_match.group(1) or "").strip()
    if not url:
        raise CommandError("Please provide a URL to download.")
    if not re.fullmatch(r"https?://\S+", url):
        raise CommandError("Please provide a valid HTTP(S) URL.")

    context = get_application_context()
    if context is None:
        raise CommandError("Media service is unavailable.")
    service = context.get("media")
    workspace = await service.create_workspace("aria")

    await event.edit(render("ARIA2", ["Initializing download...", url], footer="media | aria2"))
    try:
        argv = ["aria2c", "-d", ".", "-x", "4", "-s", "4", "--max-file-not-found", "2", "--file-allocation", "none", url]
        _, artifacts = await service.run_download(argv, workspace=workspace, timeout=600)
        if len(artifacts) != 1:
            raise CommandError("aria2c produced an unexpected number of downloadable artifacts; refusing to upload an ambiguous result.")
        (file_to_upload,) = artifacts
        up_prog = ProgressCallback(event, "Uploading to Telegram")
        await event.client.send_file(event.chat_id, file=file_to_upload.path, progress_callback=up_prog, reply_to=event.reply_to_msg_id)
        await event.delete()
    finally:
        await service.cleanup(workspace)
