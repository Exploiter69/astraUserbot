import logging
import re
import shlex
import shutil
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}rclone(?:\s+(.*))?$"


async def setup(client):
    if not shutil.which("rclone"):
        logger.warning("rclone missing. Rclone plugin disabled.")
        return
    register_cmd(client, pattern=PATTERN, handler=handle_rclone, category="media", description="Run an rclone sync/copy job. Usage: .rclone copy <src> <dest>")


async def handle_rclone(event):
    args = event.pattern_match.group(1)
    if not args:
        raise CommandError("Please provide rclone arguments (e.g. copy /src remote:dest)")
    try:
        argv = ["rclone", *shlex.split(args)]
    except ValueError:
        raise CommandError("Invalid rclone arguments.")

    await event.edit(render("RCLONE", ["Executing rclone operation.", "Running with bounded subprocess policy..."], footer="media | rclone"))
    from core.context import get_application_context
    context = get_application_context()
    subprocess = context.get("subprocess") if context else None
    if subprocess is None:
        from helpers.shell import run
        rc, out, err = await run(argv, timeout=900)
    else:
        result = await subprocess.run(argv, timeout=900)
        rc, out, err = result.returncode, result.stdout, result.stderr

    if rc != 0:
        raise CommandError(f"Rclone failed with code {rc}.\n{err[-500:]}")
    result_lines = out.strip().splitlines() if out else ["Job completed successfully with no output."]
    await event.edit(render("RCLONE", ["---"] + result_lines[-10:], footer="media | rclone"))
