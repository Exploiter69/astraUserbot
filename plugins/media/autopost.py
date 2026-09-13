import asyncio
import logging
import re

from config import config
from core.database import Database
from core.errors import CommandError
from core.registry import register_cmd
from core.scheduler import schedule_job
from helpers.hud import render
from telethon import types

logger = logging.getLogger(__name__)
PATTERN = rf"^{re.escape(config.PREFIX)}autopost(?:\s+(.*))?$"
db = Database.get("autopost")
_scheduler_task: asyncio.Task[None] | None = None
_client = None


async def _ensure_schema() -> None:
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            peer_type TEXT NOT NULL DEFAULT 'id',
            access_hash INTEGER
        );
    """)
    columns = {row[1] for row in await db.fetchall("PRAGMA table_info(posts)")}
    if "peer_type" not in columns:
        await db.execute("ALTER TABLE posts ADD COLUMN peer_type TEXT NOT NULL DEFAULT 'id'")
    if "access_hash" not in columns:
        await db.execute("ALTER TABLE posts ADD COLUMN access_hash INTEGER")


def _peer_metadata(input_chat) -> tuple[str, int | None]:
    if isinstance(input_chat, types.InputPeerUser):
        return "user", input_chat.access_hash
    if isinstance(input_chat, types.InputPeerChannel):
        return "channel", input_chat.access_hash
    if isinstance(input_chat, types.InputPeerChat):
        return "chat", None
    if isinstance(input_chat, types.InputPeerSelf):
        return "self", None
    return "id", None


def _input_peer(chat_id: int, peer_type: str, access_hash: int | None):
    if peer_type == "user" and access_hash is not None:
        return types.InputPeerUser(chat_id, access_hash)
    if peer_type == "channel" and access_hash is not None:
        return types.InputPeerChannel(chat_id, access_hash)
    if peer_type == "chat":
        return types.InputPeerChat(chat_id)
    return chat_id


async def setup(client):
    await _ensure_schema()

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

    input_chat = await event.get_input_chat()
    peer_type, access_hash = _peer_metadata(input_chat)
    await db.execute(
        "INSERT INTO posts (chat_id, message, peer_type, access_hash) VALUES (?, ?, ?, ?)",
        (event.chat_id, msg, peer_type, access_hash),
    )
    await event.edit(render(
        title="AUTOPOST",
        rows=["Scheduled new hourly auto-post.", f"Preview: {msg[:30]}..."],
        footer="media | autopost",
    ))


async def autopost_worker():
    rows = await db.fetchall("SELECT id, chat_id, message, peer_type, access_hash FROM posts")
    for post_id, chat_id, message, peer_type, access_hash in rows:
        try:
            target = _input_peer(chat_id, peer_type, access_hash)
            await _client.send_message(target, message)
        except Exception as exc:
            logger.error(
                "Autopost failed for post=%s chat=%s peer_type=%s: %s",
                post_id,
                chat_id,
                peer_type,
                exc,
            )
