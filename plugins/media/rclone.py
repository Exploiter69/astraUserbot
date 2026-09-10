import re
import shutil
import logging
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.shell import run
from config import config

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}rclone(?:\s+(.*))?$"

async def setup(client):
    if not shutil.which("rclone"):
        logger.warning("rclone missing. Rclone plugin disabled.")
        return
    register_cmd(
        client, 
        pattern=PATTERN, 
        handler=handle_rclone, 
        category="media", 
        description="Run an rclone sync/copy job. Usage: .rclone copy <src> <dest>"
    )

async def handle_rclone(event):
    args = event.pattern_match.group(1)
    if not args:
        raise CommandError("Please provide rclone arguments (e.g. copy /src remote:dest)")
        
    await event.edit(render(
        title="RCLONE", 
        rows=[f"Executing: rclone {args}", "Running in background..."], 
        footer="media | rclone"
    ))
    
    # 15 minute timeout for large syncs
    import shlex
    try:
        argv = ["rclone", *shlex.split(args)]
    except ValueError as exc:
        raise CommandError(f"Invalid rclone arguments: {exc}") from exc
    rc, out, err = await run(argv, timeout=900)
    
    if rc != 0:
        raise CommandError(f"Rclone failed with code {rc}:\n{err[-500:]}")
        
    result_lines = out.strip().split("\n") if out else ["Job completed successfully with no output."]
    
    await event.edit(render(
        title="RCLONE",
        rows=["---"] + result_lines[-10:], 
        footer="media | rclone"
    ))
