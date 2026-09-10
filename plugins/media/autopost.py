import re
import logging
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from core.scheduler import schedule_job
from helpers.hud import render
from config import config

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}autopost(?:\s+(.*))?$"
db = Database.get("autopost")

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message TEXT NOT NULL
        );
    """)
    
    register_cmd(
        client, 
        pattern=PATTERN, 
        handler=handle_autopost, 
        category="media", 
        description="Schedule an auto-post in the current chat. Usage: .autopost <message> or .autopost rm <id>"
    )
    
    global _client
    _client = client
    # Hourly schedule
    schedule_job(3600, autopost_worker, "media_autopost")

async def handle_autopost(event):
    msg = event.pattern_match.group(1)
    if not msg:
        rows = await db.fetchall("SELECT id, message FROM posts WHERE chat_id = ?", (event.chat_id,))
        if not rows:
            await event.edit(render(title="AUTOPOST", rows=["No scheduled posts for this chat."], footer="media | autopost"))
            return
            
        display = ["Scheduled Posts:", "---"]
        for r in rows:
            display.append(f"[{r[0]}] {r[1][:30]}...")
        await event.edit(render(title="AUTOPOST", rows=display, footer="media | autopost"))
        return
        
    if msg.startswith("rm "):
        try:
            pid = int(msg.split()[1])
            await db.execute("DELETE FROM posts WHERE id = ? AND chat_id = ?", (pid, event.chat_id))
            await event.edit(render(title="AUTOPOST", rows=[f"Deleted post ID {pid}."], footer="media | autopost"))
        except (IndexError, ValueError):
            raise CommandError("Invalid ID format. Use: .autopost rm <id>")
        return

    await db.execute("INSERT INTO posts (chat_id, message) VALUES (?, ?)", (event.chat_id, msg))
    await event.edit(render(
        title="AUTOPOST", 
        rows=["Scheduled new hourly auto-post.", f"Preview: {msg[:30]}..."], 
        footer="media | autopost"
    ))

async def autopost_worker():
    rows = await db.fetchall("SELECT chat_id, message FROM posts")
    for chat_id, message in rows:
        try:
            await _client.send_message(chat_id, message)
        except Exception as e:
            logger.error(f"Autopost failed for chat {chat_id}: {e}")
