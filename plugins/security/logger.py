import logging
import re
import time
from collections import OrderedDict
from telethon import events
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from config import config

db = Database.get("logger")
PATTERN = rf"^{re.escape(config.PREFIX)}(logger|mirror|setlogger|read)(?:\s+(.*))?$"
logger = logging.getLogger("astra.plugins.logger")
_CACHE_CAPACITY = 500
_PERSISTED_CAPACITY = 5000
_RETENTION_SECONDS = 7 * 86400
_CLEANUP_INTERVAL = 300.0
_MAX_DEST_ROWS = 100
_last_cleanup = 0.0

class LRUCache:
    def __init__(self, capacity: int):
        self.cache = OrderedDict()
        self.capacity = capacity
    def get(self, key):
        value = self.cache.get(key)
        if value is not None:
            self.cache.move_to_end(key)
        return value
    def put(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

_msg_cache = LRUCache(_CACHE_CAPACITY)

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS log_settings (key TEXT PRIMARY KEY, val INTEGER);
        INSERT OR IGNORE INTO log_settings (key, val) VALUES ('logger', 0), ('mirror', 0), ('channel', 0);
        CREATE TABLE IF NOT EXISTS message_cache (message_id INTEGER PRIMARY KEY, sender_id INTEGER, text TEXT, created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_message_cache_created ON message_cache(created_at);
    """)
    await _cleanup_cache(time.time(), force=True)
    register_cmd(client, PATTERN, handle_logger, "security", "Forensic message logger.")
    client.add_event_handler(cache_watcher, events.NewMessage(incoming=True, func=lambda e: e.is_private))
    client.add_event_handler(delete_watcher, events.MessageDeleted())
    client.add_event_handler(edit_watcher, events.MessageEdited(incoming=True, func=lambda e: e.is_private))

async def _cleanup_cache(now: float, *, force: bool = False):
    global _last_cleanup
    if not force and now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    cutoff = now - _RETENTION_SECONDS
    try:
        await db.execute("DELETE FROM message_cache WHERE created_at < ?", (cutoff,))
        await db.execute("DELETE FROM message_cache WHERE rowid IN (SELECT rowid FROM message_cache ORDER BY created_at DESC LIMIT -1 OFFSET ?)", (_PERSISTED_CAPACITY,))
    except Exception:
        logger.exception("Logger message-cache cleanup failed")

async def get_log_chat():
    row = await db.fetchone("SELECT val FROM log_settings WHERE key = 'channel'")
    return row[0] if row and row[0] != 0 else "me"

async def handle_logger(event):
    cmd = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip().lower()
    if cmd in ("logger", "mirror"):
        if arg not in {"on", "off"}:
            raise CommandError(f"Usage: .{cmd} on|off")
        state = 1 if arg == "on" else 0
        await db.execute("UPDATE log_settings SET val = ? WHERE key = ?", (state, cmd))
        await event.edit(render("LOGGER CONFIG", [f"{cmd.upper()}: {'ENABLED' if state else 'DISABLED'}"]))
    elif cmd == "setlogger":
        await db.execute("UPDATE log_settings SET val = ? WHERE key = 'channel'", (event.chat_id,))
        await event.edit(render("LOGGER CONFIG", [f"Log destination set to current chat ({event.chat_id})."]))
    elif cmd == "read":
        await event.client.send_read_acknowledge(event.chat_id)
        await event.edit(render("LOGGER", ["Marked current chat as read."]))

async def cache_watcher(event):
    logger_cfg = await db.fetchone("SELECT val FROM log_settings WHERE key = 'logger'")
    mirror_cfg = await db.fetchone("SELECT val FROM log_settings WHERE key = 'mirror'")
    if not ((logger_cfg and logger_cfg[0] == 1) or (mirror_cfg and mirror_cfg[0] == 1)):
        return
    now = time.time()
    if mirror_cfg and mirror_cfg[0] == 1:
        await event.forward_to(await get_log_chat())
    if logger_cfg and logger_cfg[0] == 1:
        _msg_cache.put(event.id, {"text": event.text, "sender": event.sender_id})
        await db.execute("INSERT OR REPLACE INTO message_cache(message_id, sender_id, text, created_at) VALUES (?, ?, ?, ?)", (event.id, event.sender_id, event.text, now))
        await _cleanup_cache(now)

async def _get_cached(msg_id):
    cached = _msg_cache.get(msg_id)
    if cached:
        return cached
    row = await db.fetchone("SELECT sender_id, text FROM message_cache WHERE message_id = ?", (msg_id,))
    if not row:
        return None
    cached = {"sender": row[0], "text": row[1]}
    _msg_cache.put(msg_id, cached)
    return cached

async def delete_watcher(event):
    log_cfg = await db.fetchone("SELECT val FROM log_settings WHERE key = 'logger'")
    if not log_cfg or log_cfg[0] == 0:
        return
    log_chat = await get_log_chat()
    for msg_id in event.deleted_ids:
        cached = await _get_cached(msg_id)
        if cached:
            msg = render("ANTI-DELETE GUARDIAN", [f"Sender ID: {cached['sender']}", "---", cached['text'] or "[Media/No Text]"])
            await event.client.send_message(log_chat, msg)
        await db.execute("DELETE FROM message_cache WHERE message_id = ?", (msg_id,))

async def edit_watcher(event):
    log_cfg = await db.fetchone("SELECT val FROM log_settings WHERE key = 'logger'")
    if not log_cfg or log_cfg[0] == 0:
        return
    log_chat = await get_log_chat()
    cached = await _get_cached(event.id)
    if cached:
        msg = render("ANTI-EDIT GUARDIAN", [f"Sender ID: {event.sender_id}", "---", "[BEFORE]", cached["text"] or "[Empty]", "---", "[AFTER]", event.text or "[Empty]"])
        await event.client.send_message(log_chat, msg)
        _msg_cache.put(event.id, {"text": event.text, "sender": event.sender_id})
        await db.execute("UPDATE message_cache SET text = ? WHERE message_id = ?", (event.text, event.id))
