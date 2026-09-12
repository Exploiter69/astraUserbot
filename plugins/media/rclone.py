import logging
import re
import shlex
import shutil
from core.context import get_application_context
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
    register_cmd(client, pattern=PATTERN, handler=handle_rclone, category="media", description="Run an rclone copy/sync job. Usage: .rclone copy <src> <dest>")


async def handle_rclone(event):
    args = event.pattern_match.group(1)
    if not args:
        raise CommandError("Please provide rclone arguments (e.g. copy /src remote:dest)")
    try:
        tokens = shlex.split(args)
    except ValueError as exc:
        raise CommandError("Invalid rclone arguments.") from exc
    if not tokens:
        raise CommandError("Please provide an rclone operation.")

    operation = tokens[0].lower()
    if operation not in {"copy", "copyto", "sync"}:
        raise CommandError("Allowed rclone operations: copy, copyto, sync.")

    if operation == "sync" and len(tokens) < 3:
        raise CommandError("Usage: .rclone sync <source> <destination>")
    if operation in {"copy", "copyto"} and len(tokens) < 3:
        raise CommandError(f"Usage: .rclone {operation} <source> <destination>")

    context = get_application_context()
    if context is None:
        raise CommandError("Media service is unavailable.")
    service = context.get("media")
    workspace = await service.create_workspace("rclone")

    await event.edit(render("RCLONE", ["Executing permitted rclone operation.", "Running with bounded subprocess policy..."], footer="media | rclone"))
    try:
        result = await service.run_rclone(["rclone", *tokens], workspace=workspace, timeout=900)
        if result.returncode != 0:
            raise CommandError(f"Rclone failed with code {result.returncode}.\n{result.stderr[-500:]}")
        result_lines = result.stdout.strip().splitlines() if result.stdout else ["Job completed successfully with no output."]
        await event.edit(render("RCLONE", ["---"] + result_lines[-10:], footer="media | rclone"))
    finally:
        await service.cleanup(workspace)
