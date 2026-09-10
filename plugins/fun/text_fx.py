import re
import random
from core.registry import register_cmd
from helpers.hud import render
from config import config
import asyncio

PATTERN = rf"^{re.escape(config.PREFIX)}(mock|owo|ghost|spam|shrug)(?:\s+(.*))?$"

async def setup(client):
    register_cmd(client, PATTERN, handle_textfx, "fun", "Text effects and chat automation.")

async def handle_textfx(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2) or ""
    
    if cmd == "mock":
        res = "".join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(arg))
        await event.edit(res)
    elif cmd == "owo":
        res = arg.replace("r", "w").replace("l", "w").replace("R", "W").replace("L", "W") + " uwu"
        await event.edit(res)
    elif cmd == "shrug":
        await event.edit(f"{arg} ¯\\_(ツ)_/¯")
    elif cmd == "ghost":
        parts = arg.split(maxsplit=1)
        if len(parts) < 2: return
        await event.edit(parts[1])
        await asyncio.sleep(int(parts[0]))
        await event.delete()
    elif cmd == "spam":
        parts = arg.split(maxsplit=2)
        if len(parts) < 3: return
        count, delay, txt = int(parts[0]), float(parts[1]), parts[2]
        await event.delete()
        for _ in range(min(count, 50)): # Hard limit to prevent ban
            await event.client.send_message(event.chat_id, txt)
            await asyncio.sleep(delay)
