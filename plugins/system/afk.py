import asyncio
import re
import time
from collections import OrderedDict

from telethon import events
from core.registry import register_cmd
from core.database import Database
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}afk(?:\s+(.*))?$"
db = Database.get("afk")
_WARN_COOLDOWN = 60.0
_WARN_CACHE_LIMIT = 1024
_last_replies: OrderedDict[int, float] = OrderedDict()


def _allow_reply(sender_id: int, now: float) -> bool:
    cutoff = now - _WARN_COOLDOWN
    for key, timestamp in list(_last_replies.items()):
        if timestamp < cutoff:
            _last_replies.pop(key, None)
        else:
            break
    previous = _last_replies.get(sender_id)
    if previous is not None and now - previous < _WARN_COOLDOWN:
        return False
    _last_replies[sender_id] = now
    _last_replies.move_to_end(sender_id)
    while len(_last_replies) > _WARN_CACHE_LIMIT:
        _last_replies.popitem(last=False)
    return True


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
    register_cmd(client, pattern=PATTERN, handler=handle_afk, category="system", description="Toggle AFK status and auto-reply.")
    client.add_event_handler(afk_watcher, events.NewMessage(incoming=True))
    client.add_event_handler(afk_breaker, events.NewMessage(outgoing=True))


async def handle_afk(event):
    reason = event.pattern_match.group(1) or "No reason provided"
    await db.execute("UPDATE afk_state SET is_afk = 1, reason = ?, timestamp = ? WHERE id = 1", (reason, time.time()))
    _last_replies.clear()
    await event.edit(render("AFK ENABLED", [f"Reason: {reason}"], footer="system | afk"))


async def afk_watcher(event):
    if not event.is_private and not event.mentioned:
        return
    row = await db.fetchone("SELECT is_afk, reason, timestamp FROM afk_state WHERE id = 1")
    if not row or row[0] != 1 or not event.sender_id:
        return
    now = time.time()
    if not _allow_reply(event.sender_id, now):
        return
    reason, since = row[1], row[2]
    elapsed = now - since
    mins, secs = divmod(int(elapsed), 60)
    hours, mins = divmod(mins, 60)
    time_str = f"{hours}h {mins}m" if hours else f"{mins}m {secs}s"
    msg = render(
        "AFK ALERT",
        ["I am currently away from the keyboard.", "---", f"Reason: {reason}", f"Since: {time_str} ago"],
        footer="auto-reply",
    )
    await event.reply(msg)


async def afk_breaker(event):
    if event.text and event.text.startswith(f"{config.PREFIX}afk"):
        return
    row = await db.fetchone("SELECT is_afk FROM afk_state WHERE id = 1")
    if row and row[0] == 1:
        await db.execute("UPDATE afk_state SET is_afk = 0, reason = NULL, timestamp = 0 WHERE id = 1")
        _last_replies.clear()
        msg = await event.respond(render("AFK DISABLED", ["Welcome back. AFK status has been cleared."], footer="auto-reply"))
        await asyncio.sleep(3)
        await msg.delete()
