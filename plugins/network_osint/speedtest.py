import re
import shutil
import logging

from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}speedtest$"

async def setup(client):
    binary = shutil.which("speedtest-cli") or shutil.which("speedtest")
    if not binary:
        logger.warning("speedtest-cli binary missing. Speedtest plugin disabled.")
        return

    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_speedtest,
        category="network_osint",
        description="Run an internet speed test."
    )

async def handle_speedtest(event):
    context = get_application_context()
    if context is None:
        raise CommandError("Subprocess service is unavailable.")
    subprocess = context.get("subprocess")

    await event.edit(render(
        title="SPEEDTEST",
        rows=["Running speed test in background...", "This may take up to 45 seconds."],
        footer="network_osint | speedtest"
    ))

    binary = shutil.which("speedtest-cli") or shutil.which("speedtest")
    if not binary:
        raise CommandError("Speedtest binary is unavailable.")

    try:
        result = await subprocess.run([binary, "--simple"], timeout=90, max_output_bytes=64 * 1024)
    except Exception as exc:
        raise CommandError("Speedtest execution failed.") from exc

    if result.returncode != 0:
        raise CommandError(f"Speedtest failed: {result.stderr.strip() or 'Unknown error'}")

    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    await event.edit(render(
        title="SPEEDTEST RESULTS",
        rows=lines if lines else ["No output received."],
        footer="network_osint | speedtest"
    ))
