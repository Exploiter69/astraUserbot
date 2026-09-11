import re
import asyncio
from telethon.tl.functions.channels import EditBannedRequest, EditAdminRequest, ToggleSlowModeRequest
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
        if arg and arg.isdigit():
            limit = min(int(arg), 1000)
        messages = []
        async for msg in event.client.iter_messages(event.chat_id, limit=limit):
            if cmd == "purgeme" and msg.sender_id != config.OWNER_ID:
                continue
            if msg.id != event.id:
                messages.append(msg.id)
        if messages:
            await event.client.delete_messages(event.chat_id, messages)
        msg = await event.respond(render("PURGE", [f"Cleared {len(messages)} messages."]))
        await asyncio.sleep(2)
        await msg.delete()

    elif cmd == "zombies":
        await event.edit(render("ZOMBIE SCAN", ["Scanning for deleted accounts..."]))
        zombies = []
        async for user in event.client.iter_participants(event.chat_id):
            if user.deleted:
                zombies.append(user)
        for zombie in zombies:
            try:
                await event.client(EditBannedRequest(
                    event.chat_id,
                    zombie.id,
                    ChatBannedRights(until_date=None, view_messages=True),
                ))
            except Exception:
                continue
        await event.edit(render("ZOMBIE SCAN", [f"Purged {len(zombies)} deleted accounts."]))

    elif cmd in ("promote", "demote"):
        target = await resolve_target(event)
        if cmd == "promote":
            rights = ChatAdminRights(
                add_admins=False,
                invite_users=True,
                change_info=False,
                ban_users=True,
                delete_messages=True,
                pin_messages=True,
            )
            await event.client(EditAdminRequest(event.chat_id, target.id, rights, rank=arg or "Admin"))
            await event.edit(render("ADMIN OPS", [f"Promoted {target.id}"]))
        else:
            rights = ChatAdminRights(
                add_admins=False,
                invite_users=False,
                change_info=False,
                ban_users=False,
                delete_messages=False,
                pin_messages=False,
            )
            await event.client(EditAdminRequest(event.chat_id, target.id, rights, rank=""))
            await event.edit(render("ADMIN OPS", [f"Demoted {target.id}"]))

    elif cmd == "slow":
        if not arg or not arg.strip().lstrip("-").isdigit():
            raise CommandError("Usage: .slow <seconds> (0 disables slow mode)")
        seconds = int(arg.strip())
        if seconds < 0 or seconds > 86400:
            raise CommandError("Slow mode must be between 0 and 86400 seconds.")
        await event.client(ToggleSlowModeRequest(event.chat_id, seconds))
        status = "disabled" if seconds == 0 else f"set to {seconds}s"
        await event.edit(render("ADMIN OPS", [f"Slow mode {status}."]))

    elif cmd == "kickme":
        await event.edit(render("ADMIN OPS", ["Leaving chat..."]))
        await event.client.delete_dialog(event.chat_id)
