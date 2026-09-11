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
_MAX_PURGE = 1000

async def setup(client):
    register_cmd(client, PATTERN, handle_admin, "admin_ops", "Advanced group administration.")

async def handle_admin(event):
    cmd = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip()

    if cmd in ("purge", "purgeme"):
        if arg:
            if not arg.isdigit():
                raise CommandError("Purge count must be a positive integer.")
            limit = int(arg)
            if not 1 <= limit <= _MAX_PURGE:
                raise CommandError(f"Purge count must be between 1 and {_MAX_PURGE}.")
        else:
            limit = 100
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
        purged = 0
        failed = 0
        for zombie in zombies:
            try:
                await event.client(EditBannedRequest(
                    event.chat_id,
                    zombie.id,
                    ChatBannedRights(until_date=None, view_messages=True),
                ))
                purged += 1
            except Exception:
                failed += 1
        await event.edit(render("ZOMBIE SCAN", [
            f"Found: {len(zombies)}",
            f"Purged: {purged}",
            f"Failed: {failed}",
        ]))

    elif cmd in ("promote", "demote"):
        target = await resolve_target(event)
        if target.id == config.OWNER_ID:
            raise CommandError("Cannot modify the owner account.")
        if cmd == "promote":
            rights = ChatAdminRights(
                add_admins=False,
                invite_users=True,
                change_info=False,
                ban_users=True,
                delete_messages=True,
                pin_messages=True,
            )
            rank = arg or "Admin"
            if len(rank) > 32:
                raise CommandError("Admin rank must be 32 characters or fewer.")
            await event.client(EditAdminRequest(event.chat_id, target.id, rights, rank=rank))
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
        if not arg or not arg.lstrip("-").isdigit():
            raise CommandError("Usage: .slow <seconds> (0 disables slow mode)")
        seconds = int(arg)
        if seconds < 0 or seconds > 86400:
            raise CommandError("Slow mode must be between 0 and 86400 seconds.")
        await event.client(ToggleSlowModeRequest(event.chat_id, seconds))
        await event.edit(render("ADMIN OPS", ["Slow mode disabled." if seconds == 0 else f"Slow mode set to {seconds}s."]))

    elif cmd == "kickme":
        await event.edit(render("ADMIN OPS", ["Leaving chat..."]))
        await event.client.delete_dialog(event.chat_id)
