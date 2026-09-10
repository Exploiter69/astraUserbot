import re
import time
from telethon import events
from telethon.tl.functions.channels import EditBannedRequest, EditAdminRequest
from telethon.tl.types import ChatBannedRights, ChatAdminRights
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.entity import resolve_target
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(purge|purgeme|zombies|promote|demote|slow|kickme)(?:\s+(.*))?$"

async def setup(client):
    register_cmd(client, PATTERN, handle_admin, "admin_ops", "Advanced group administration.")

async def handle_admin(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2)
    
    if cmd in ("purge", "purgeme"):
        limit = 100
        if arg and arg.isdigit(): limit = int(arg)
        # Simplified bulk purge for brevity; handles standard ID iteration
        messages = []
        async for msg in event.client.iter_messages(event.chat_id, limit=limit):
            if cmd == "purgeme" and msg.sender_id != config.OWNER_ID: continue
            if msg.id != event.id: messages.append(msg.id)
        if messages: await event.client.delete_messages(event.chat_id, messages)
        msg = await event.respond(render("PURGE", [f"Cleared {len(messages)} messages."]))
        import asyncio; await asyncio.sleep(2); await msg.delete()
        
    elif cmd == "zombies":
        await event.edit(render("ZOMBIE SCAN", ["Scanning for deleted accounts..."]))
        zombies = []
        async for user in event.client.iter_participants(event.chat_id):
            if user.deleted: zombies.append(user)
        for z in zombies:
            try:
                await event.client(EditBannedRequest(event.chat_id, z.id, ChatBannedRights(until_date=None, view_messages=True)))
            except Exception: pass
        await event.edit(render("ZOMBIE SCAN", [f"Purged {len(zombies)} deleted accounts."]))
        
    elif cmd == "promote":
        target = await resolve_target(event)
        rights = ChatAdminRights(add_admins=False, invite_users=True, change_info=False, ban_users=True, delete_messages=True, pin_messages=True)
        await event.client(EditAdminRequest(event.chat_id, target.id, rights, rank=arg or "Admin"))
        await event.edit(render("ADMIN OPS", [f"Promoted {target.id}"]))
        
    elif cmd == "kickme":
        await event.edit(render("ADMIN OPS", ["Leaving chat..."]))
        await event.client.delete_dialog(event.chat_id)
