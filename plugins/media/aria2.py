import re
import shutil
import logging
from pathlib import Path
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
    url = event.pattern_match.group(1)
    if not url:
        raise CommandError("Please provide a URL to download.")

    from core.context import get_application_context
    context = get_application_context()
    workspace_service = context.get("workspace") if context else None
    subprocess = context.get("subprocess") if context else None
    workspace = await workspace_service.create("aria") if workspace_service else None
    out_dir = workspace.path if workspace else Path("data/cache") / "aria-fallback"
    out_dir.mkdir(parents=True, exist_ok=True)

    await event.edit(render("ARIA2", ["Initializing download...", url], footer="media | aria2"))
    try:
        argv = ["aria2c", "-d", str(out_dir), "-x", "4", "-s", "4", url]
        if subprocess:
            result = await subprocess.run(argv, timeout=600)
            rc, out, err = result.returncode, result.stdout, result.stderr
        else:
            from helpers.shell import run
            rc, out, err = await run(argv, timeout=600)
        if rc != 0:
            raise CommandError(f"Aria2c failed: {err[-500:]}")

        downloaded_files = [path for path in out_dir.iterdir() if path.is_file()]
        if not downloaded_files:
            raise CommandError("No files downloaded.")
        file_to_upload = downloaded_files[0]
        up_prog = ProgressCallback(event, "Uploading to Telegram")
        await event.client.send_file(event.chat_id, file=file_to_upload, progress_callback=up_prog, reply_to=event.reply_to_msg_id)
        await event.delete()
    finally:
        if workspace_service and workspace:
            await workspace_service.cleanup(workspace)
        elif out_dir.exists() and out_dir.name == "aria-fallback":
            shutil.rmtree(out_dir, ignore_errors=True)
