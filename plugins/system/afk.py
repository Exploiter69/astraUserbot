import re
import time
from telethon import events
from core.registry import register_cmd
from core.database import Database
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}afk(?:\s+(.*))?$"
db = Database.get("afk")

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS afk_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            is_afk INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            timestamp REAL
        );
        INSERT OR IGNORE INTO afk_state (id, is_afk, reason, timestamp) VALUES (1, 0, NULL, 0);
    """)
    
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_afk,
        category="system",
        description="Toggle AFK status and auto-reply."
    )
    
    # Register an incoming message watcher directly to client to handle auto-replies
    client.add_event_handler(afk_watcher, events.NewMessage(incoming=True))
    # Register an outgoing message watcher to auto-disable AFK
    client.add_event_handler(afk_breaker, events.NewMessage(outgoing=True))

async def handle_afk(event):
    reason = event.pattern_match.group(1) or "No reason provided"
    now = time.time()
    
    await db.execute(
        "UPDATE afk_state SET is_afk = 1, reason = ?, timestamp = ? WHERE id = 1",
        (reason, now)
    )
    
    await event.edit(render(
        title="AFK ENABLED",
        rows=[f"Reason: {reason}"],
        footer="system | afk"
    ))

async def afk_watcher(event):
    if not event.is_private and not event.mentioned:
        return
        
    row = await db.fetchone("SELECT is_afk, reason, timestamp FROM afk_state WHERE id = 1")
    if row and row[0] == 1:
        reason, since = row[1], row[2]
        elapsed = time.time() - since
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        time_str = f"{hours}h {mins}m" if hours else f"{mins}m {secs}s"
        
        msg = render(
            title="AFK ALERT",
            rows=["I am currently away from the keyboard.", "---", f"Reason: {reason}", f"Since: {time_str} ago"],
            footer="auto-reply"
        )
        await event.reply(msg)

async def afk_breaker(event):
    if event.text and event.text.startswith(f"{config.PREFIX}afk"):
        return
        
    row = await db.fetchone("SELECT is_afk FROM afk_state WHERE id = 1")
    if row and row[0] == 1:
        await db.execute("UPDATE afk_state SET is_afk = 0, reason = NULL, timestamp = 0 WHERE id = 1")
        msg = await event.respond(render(
            title="AFK DISABLED",
            rows=["Welcome back. AFK status has been cleared."],
            footer="system | afk"
        ))
        # Auto-delete the notification after 3 seconds
        import asyncio
        await asyncio.sleep(3)
        await msg.delete()
