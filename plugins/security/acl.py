import re
from telethon import events
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.entity import resolve_target
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(block|unblock)(?:\s+(.*))?$"
db = Database.get("acl")

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS blocklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT
        );
    """)
    
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_acl,
        category="security",
        description="Manage user blocklists. Usage: .block [reason] / .unblock"
    )
    
    # Watcher that runs on incoming messages to enforce the ACL silently
    client.add_event_handler(acl_watcher, events.NewMessage(incoming=True))

async def handle_acl(event):
    command = event.pattern_match.group(1).lower()
    reason = event.pattern_match.group(2) or "No reason provided"
    
    try:
        target = await resolve_target(event)
    except Exception:
        raise CommandError("Could not resolve target user. Reply to them or provide an ID.")
        
    if target.id == config.OWNER_ID or target.id == event.client.uid:
        raise CommandError("Cannot block the bot owner.")

    if command == "block":
        await db.execute("INSERT OR REPLACE INTO blocklist (user_id, reason) VALUES (?, ?)", (target.id, reason))
        await event.edit(render(
            title="ACL UPDATED",
            rows=[f"Target: {target.id}", "Status: BLOCKED", f"Reason: {reason}"],
            footer="security | acl"
        ))
    elif command == "unblock":
        await db.execute("DELETE FROM blocklist WHERE user_id = ?", (target.id,))
        await event.edit(render(
            title="ACL UPDATED",
            rows=[f"Target: {target.id}", "Status: UNBLOCKED"],
            footer="security | acl"
        ))

async def acl_watcher(event):
    if not event.is_private:
        return
        
    user_id = event.sender_id
    if not user_id:
        return
        
    row = await db.fetchone("SELECT reason FROM blocklist WHERE user_id = ?", (user_id,))
    if row:
        # Silently delete the message if the user is in the database
        try:
            await event.delete()
        except Exception:
            pass
