import asyncio
import logging
import re

from config import config
from core.database import Database
from core.errors import CommandError
from core.registry import register_cmd
from core.scheduler import schedule_job
from helpers.hud import render

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}autopost(?:\s+(.*))?$"
db = Database.get("autopost")
_scheduler_task: asyncio.Task[None] | None = None
_client = None


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
        description="Schedule an auto-post in the current chat. Usage: .autopost <message> or .autopost rm <id>",
    )

    global _client, _scheduler_task
    _client = client
    _scheduler_task = schedule_job(3600, autopost_worker, "media_autopost")


async def shutdown(client):
    """Stop the scheduler before this plugin's resources are unloaded."""
    global _client, _scheduler_task
    task = _scheduler_task
    _scheduler_task = None
    _client = None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def handle_autopost(event):
    msg = event.pattern_match.group(1)
    if not msg:
        rows = await db.fetchall("SELECT id, message FROM posts WHERE chat_id = ?", (event.chat_id,))
        if not rows:
            await event.edit(render(title="AUTOPOST", rows=["No scheduled posts for this chat."], footer="media | autopost"))
            return

        display = ["Scheduled Posts:", "---"]
        for r in rows[:50]:
            preview = r[1][:30] + ("..." if len(r[1]) > 30 else "")
            display.append(f"[{r[0]}] {preview}")
        await event.edit(render(title="AUTOPOST", rows=display, footer="media | autopost"))
        return

    if msg.startswith("rm "):
        try:
            parts = msg.split(maxsplit=1)
            pid = int(parts[1])
        except (IndexError, ValueError):
            raise CommandError("Invalid ID format. Use: .autopost rm <id>")
        cursor = await db.execute(
            "DELETE FROM posts WHERE id = ? AND chat_id = ?",
            (pid, event.chat_id),
        )
        if cursor.rowcount == 0:
            raise CommandError(f"No scheduled post {pid} exists in this chat.")
        await event.edit(render(title="AUTOPOST", rows=[f"Deleted post ID {pid}."], footer="media | autopost"))
        return

    msg = msg.strip()
    if not msg:
        raise CommandError("Post message cannot be empty.")
    if len(msg) > 4000:
        raise CommandError("Post message is too long (max 4000 characters).")

    await db.execute("INSERT INTO posts (chat_id, message) VALUES (?, ?)", (event.chat_id, msg))
    await event.edit(render(
        title="AUTOPOST",
        rows=["Scheduled new hourly auto-post.", f"Preview: {msg[:30]}..."],
        footer="media | autopost",
    ))


async def autopost_worker():
    rows = await db.fetchall("SELECT chat_id, message FROM posts")
    for chat_id, message in rows:
        try:
            await _client.send_message(chat_id, message)
        except Exception as exc:
            logger.error("Autopost failed for chat %s: %s", chat_id, exc)
