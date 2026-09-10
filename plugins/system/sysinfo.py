import re

from core.registry import register_cmd
from helpers.hud import render
from helpers.shell import run
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
    await event.edit(render(title="SYSINFO", rows=["Gathering telemetry..."]))

    rc_uname, out_uname, _ = await run(["uname", "-r"])
    rc_uptime, out_uptime, _ = await run(["uptime", "-p"])
    rc_mem, out_mem, _ = await run(["free", "-m"])

    os_info = out_uname.strip() if rc_uname == 0 else "Unknown"
    uptime_info = out_uptime.strip() if rc_uptime == 0 else "Unknown"
    if rc_mem == 0:
        mem_line = next((line for line in out_mem.splitlines() if line.startswith("Mem:")), "")
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
