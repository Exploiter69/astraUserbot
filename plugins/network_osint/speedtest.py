import re
import shutil
import logging
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.shell import run
from helpers.concurrency import CPU_BOUND
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
    await event.edit(render(
        title="SPEEDTEST",
        rows=["Running speed test in background...", "This may take up to 45 seconds."],
        footer="network_osint | speedtest"
    ))
    
    binary = shutil.which("speedtest-cli") or shutil.which("speedtest")
    async with CPU_BOUND:
        rc, out, err = await run([binary, "--simple"], timeout=90)
        
    if rc != 0:
        raise CommandError(f"Speedtest failed: {err.strip() or 'Unknown error'}")
        
    lines = [line.strip() for line in out.strip().split("\n") if line.strip()]
    await event.edit(render(
        title="SPEEDTEST RESULTS",
        rows=lines if lines else ["No output received."],
        footer="network_osint | speedtest"
    ))
