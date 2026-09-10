import re
import time
from telethon import events
from core.registry import register_cmd
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}ping$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_ping,
        category="system",
        description="Check userbot latency and responsiveness."
    )

async def handle_ping(event):
    start = time.perf_counter()
    # Perform a dummy edit to measure Telegram API round-trip latency
    await event.edit("...") 
    elapsed = (time.perf_counter() - start) * 1000
    
    await event.edit(render(
        title="PING",
        rows=[f"Latency: {elapsed:.2f} ms", "Status: Operational"],
        footer="system | ping"
    ))
