import asyncio
import re

from core.context import get_application_context
from core.registry import register_cmd
from helpers.hud import render
from core.errors import CommandError
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}sysinfo$"


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_sysinfo,
        category="system",
        description="Display host OS and hardware telemetry.",
    )


async def handle_sysinfo(event):
    context = get_application_context()
    if context is None:
        raise CommandError("Subprocess service is unavailable.")
    subprocess = context.get("subprocess")

    await event.edit(render(title="SYSINFO", rows=["Gathering telemetry..."]))

    try:
        results = await asyncio.gather(
            subprocess.run(["uname", "-r"], timeout=5, max_output_bytes=16 * 1024),
            subprocess.run(["uptime", "-p"], timeout=5, max_output_bytes=16 * 1024),
            subprocess.run(["free", "-m"], timeout=5, max_output_bytes=16 * 1024),
        )
    except Exception as exc:
        raise CommandError("Failed to collect system telemetry.") from exc

    uname_result, uptime_result, mem_result = results
    os_info = uname_result.stdout.strip() if uname_result.returncode == 0 else "Unknown"
    uptime_info = uptime_result.stdout.strip() if uptime_result.returncode == 0 else "Unknown"

    if mem_result.returncode == 0:
        mem_line = next((line for line in mem_result.stdout.splitlines() if line.startswith("Mem:")), "")
        mem_parts = mem_line.split()
        mem_info = f"{mem_parts[2]}MB / {mem_parts[1]}MB" if len(mem_parts) >= 3 else "Unknown"
    else:
        mem_info = "Unknown"

    await event.edit(render(
        title="SYSINFO",
        rows=[
            f"Kernel: {os_info}",
            f"Uptime: {uptime_info}",
            f"Memory: {mem_info}",
            "---",
            "Engine: Astra Userbot",
            "Environment: Linux/systemd",
        ],
        footer="system | sysinfo",
    ))
