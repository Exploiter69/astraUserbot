import re
import os
import uuid
import shutil
import logging
from pathlib import Path
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.shell import run
from helpers.progress import ProgressCallback
from config import config

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}aria(?:\s+(.*))?$"

async def setup(client):
    if not shutil.which("aria2c"):
        logger.warning("aria2c missing. Aria2 plugin disabled.")
        return
    register_cmd(
        client, 
        pattern=PATTERN, 
        handler=handle_aria, 
        category="media", 
        description="Download a file via aria2c. Usage: .aria <url>"
    )

async def handle_aria(event):
    url = event.pattern_match.group(1)
    if not url:
        raise CommandError("Please provide a URL to download.")
        
    cache_dir = Path("data/cache")
    out_dir = cache_dir / f"aria_{uuid.uuid4().hex}"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    await event.edit(render(title="ARIA2", rows=["Initializing download...", url], footer="media | aria2"))
    
    rc, out, err = await run(["aria2c", "-d", str(out_dir), "-x", "4", "-s", "4", url], timeout=600)
    
    if rc != 0:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise CommandError(f"Aria2c failed: {err}")
        
    downloaded_files = list(out_dir.iterdir())
    if not downloaded_files:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise CommandError("No files downloaded.")
        
    file_to_upload = downloaded_files[0]
    
    up_prog = ProgressCallback(event, "Uploading to Telegram")
    await event.client.send_file(
        event.chat_id, 
        file=file_to_upload, 
        progress_callback=up_prog, 
        reply_to=event.reply_to_msg_id
    )
    await event.delete()
    
    shutil.rmtree(out_dir, ignore_errors=True)
