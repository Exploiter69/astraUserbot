import re
from collections import OrderedDict
from telethon import events
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from config import config

db = Database.get("logger")
PATTERN = rf"^{re.escape(config.PREFIX)}(logger|mirror|setlogger|read)(?:\s+(.*))?$"

# LRU Cache for forensic reconstruction (Message ID -> dict)
class LRUCache:
    def __init__(self, capacity: int):
        self.cache = OrderedDict()
        self.capacity = capacity
    def get(self, key):
        return self.cache.get(key)
    def put(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity: self.cache.popitem(last=False)

_msg_cache = LRUCache(500)

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS log_settings (key TEXT PRIMARY KEY, val INTEGER);
        INSERT OR IGNORE INTO log_settings (key, val) VALUES ('logger', 0), ('mirror', 0), ('channel', 0);
    """)
    register_cmd(client, PATTERN, handle_logger, "security", "Forensic message logger.")
    client.add_event_handler(cache_watcher, events.NewMessage(incoming=True, func=lambda e: e.is_private))
    client.add_event_handler(delete_watcher, events.MessageDeleted())
    client.add_event_handler(edit_watcher, events.MessageEdited(incoming=True, func=lambda e: e.is_private))

async def get_log_chat():
    row = await db.fetchone("SELECT val FROM log_settings WHERE key = 'channel'")
    return row[0] if row and row[0] != 0 else "me"

async def handle_logger(event):
    cmd = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").lower()
    
    if cmd in ("logger", "mirror"):
        state = 1 if arg == "on" else 0
        await db.execute("UPDATE log_settings SET val = ? WHERE key = ?", (state, cmd))
        await event.edit(render("LOGGER CONFIG", [f"{cmd.upper()}: {'ENABLED' if state else 'DISABLED'}"]))
        
    elif cmd == "setlogger":
        await db.execute("UPDATE log_settings SET val = ? WHERE key = 'channel'", (event.chat_id,))
        await event.edit(render("LOGGER CONFIG", [f"Log destination set to current chat ({event.chat_id})."]))
        
    elif cmd == "read":
        # Mark all as read requires iteration, simplified to current chat for safety
        await event.client.send_read_acknowledge(event.chat_id)
        await event.edit(render("LOGGER", ["Marked current chat as read."]))

async def cache_watcher(event):
    mirror_cfg = await db.fetchone("SELECT val FROM log_settings WHERE key = 'mirror'")
    if mirror_cfg and mirror_cfg[0] == 1:
        log_chat = await get_log_chat()
        await event.forward_to(log_chat)
    _msg_cache.put(event.id, {"text": event.text, "sender": event.sender_id, "media": event.media})

async def delete_watcher(event):
    log_cfg = await db.fetchone("SELECT val FROM log_settings WHERE key = 'logger'")
    if not log_cfg or log_cfg[0] == 0: return
    log_chat = await get_log_chat()
    
    for msg_id in event.deleted_ids:
        cached = _msg_cache.get(msg_id)
        if cached:
            msg = render("ANTI-DELETE GUARDIAN", [f"Sender ID: {cached['sender']}", "---", cached['text'] or "[Media/No Text]"])
            await event.client.send_message(log_chat, msg, file=cached['media'])

async def edit_watcher(event):
    log_cfg = await db.fetchone("SELECT val FROM log_settings WHERE key = 'logger'")
    if not log_cfg or log_cfg[0] == 0: return
    log_chat = await get_log_chat()
    
    cached = _msg_cache.get(event.id)
    if cached:
        msg = render("ANTI-EDIT GUARDIAN", [
            f"Sender ID: {event.sender_id}", "---", 
            "[BEFORE]", cached['text'] or "[Empty]", "---", 
            "[AFTER]", event.text or "[Empty]"
        ])
        await event.client.send_message(log_chat, msg)
        _msg_cache.put(event.id, {"text": event.text, "sender": event.sender_id, "media": event.media})
