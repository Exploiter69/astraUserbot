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
        if len(parts) != 2:
            await event.edit("Usage: .ghost <seconds> <text>")
            return
        try:
            delay = int(parts[0])
        except ValueError:
            await event.edit("Ghost delay must be a whole number of seconds.")
            return
        if not 1 <= delay <= 3600:
            await event.edit("Ghost delay must be between 1 and 3600 seconds.")
            return
        text = parts[1].strip()
        if not text:
            await event.edit("Ghost text cannot be empty.")
            return
        await event.edit(text)
        await asyncio.sleep(delay)
        await event.delete()
    elif cmd == "spam":
        parts = arg.split(maxsplit=2)
        if len(parts) != 3:
            await event.edit("Usage: .spam <count> <delay> <text>")
            return
        try:
            count = int(parts[0])
            delay = float(parts[1])
        except ValueError:
            await event.edit("Spam count must be an integer and delay a number.")
            return
        txt = parts[2].strip()
        if not 1 <= count <= 50:
            await event.edit("Spam count must be between 1 and 50.")
            return
        if not 0.1 <= delay <= 60:
            await event.edit("Spam delay must be between 0.1 and 60 seconds.")
            return
        if not txt:
            await event.edit("Spam text cannot be empty.")
            return
        if len(txt) > 4000:
            await event.edit("Spam text is too long (max 4000 characters).")
            return
        await event.delete()
        for _ in range(count):
            await event.client.send_message(event.chat_id, txt)
            await asyncio.sleep(delay)
