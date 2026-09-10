import re
import time
from telethon import events
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from helpers.entity import resolve_target
from config import config

db = Database.get("pmguard")
PATTERN = rf"^{re.escape(config.PREFIX)}(pmpermit|allow|approve|disallow|disapprove|listallowed|listdisallowed|block|unblock)(?:\s+(.*))?$"

# In-memory throttle to prevent flood-banning (user_id -> last_warning_timestamp)
_warn_throttle = {}
_cached_contacts = set()

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS pm_settings (id INTEGER PRIMARY KEY CHECK (id=1), enabled INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pm_whitelist (user_id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS pm_strikes (user_id INTEGER PRIMARY KEY, strikes INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0);
        INSERT OR IGNORE INTO pm_settings (id, enabled) VALUES (1, 0);
    """)
    register_cmd(client, PATTERN, handle_pmguard, "security", "PM Guard Gatekeeper.")
    client.add_event_handler(pm_watcher, events.NewMessage(incoming=True, func=lambda e: e.is_private))
    
    # Cache contacts on startup
    try:
        contacts = await client(GetContactsRequest(hash=0))
        for contact in contacts.users:
            _cached_contacts.add(contact.id)
    except Exception:
        pass

async def handle_pmguard(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2)
    
    if cmd == "pmpermit":
        state = 1 if arg and arg.lower() == "on" else 0
        await db.execute("UPDATE pm_settings SET enabled = ? WHERE id = 1", (state,))
        await event.edit(render("PM GUARD", [f"Status: {'ENABLED' if state else 'DISABLED'}"]))
        return
        
    if cmd in ("listallowed", "listdisallowed"):
        table = "pm_whitelist" if cmd == "listallowed" else "pm_strikes WHERE blocked = 1"
        rows = await db.fetchall(f"SELECT user_id FROM {table}")
        text_rows = [f"- {r[0]}" for r in rows] if rows else ["No records found."]
        await event.edit(render(cmd.upper(), text_rows))
        return

    target = await resolve_target(event)
    
    if cmd in ("allow", "approve"):
        await db.execute("INSERT OR REPLACE INTO pm_whitelist (user_id) VALUES (?)", (target.id,))
        await db.execute("DELETE FROM pm_strikes WHERE user_id = ?", (target.id,))
        await event.edit(render("PM GUARD", [f"User {target.id} whitelisted."]))
        
    elif cmd in ("disallow", "disapprove"):
        await db.execute("DELETE FROM pm_whitelist WHERE user_id = ?", (target.id,))
        await db.execute("DELETE FROM pm_strikes WHERE user_id = ?", (target.id,))
        await event.edit(render("PM GUARD", [f"User {target.id} authorization revoked."]))
        
    elif cmd == "block":
        await db.execute("INSERT OR REPLACE INTO pm_strikes (user_id, strikes, blocked) VALUES (?, 4, 1)", (target.id,))
        await event.client(BlockRequest(target.id))
        await event.edit(render("PM GUARD", [f"User {target.id} blocked."]))
        
    elif cmd == "unblock":
        await db.execute("DELETE FROM pm_strikes WHERE user_id = ?", (target.id,))
        await event.client(UnblockRequest(target.id))
        await event.edit(render("PM GUARD", [f"User {target.id} unblocked."]))

async def pm_watcher(event):
    if not event.is_private or event.sender_id == config.OWNER_ID or event.sender_id in _cached_contacts:
        return
        
    status = await db.fetchone("SELECT enabled FROM pm_settings WHERE id = 1")
    if not status or status[0] == 0:
        return
        
    wl = await db.fetchone("SELECT user_id FROM pm_whitelist WHERE user_id = ?", (event.sender_id,))
    if wl: return
    
    strike_data = await db.fetchone("SELECT strikes, blocked FROM pm_strikes WHERE user_id = ?", (event.sender_id,))
    strikes = strike_data[0] if strike_data else 0
    blocked = strike_data[1] if strike_data else 0
    
    if blocked: return
    
    now = time.time()
    last_warn = _warn_throttle.get(event.sender_id, 0)
    
    if strikes >= 3:
        await db.execute("UPDATE pm_strikes SET strikes = 4, blocked = 1 WHERE user_id = ?", (event.sender_id,))
        await event.reply(render("PM GUARD: BLOCKED", ["You have exceeded the warning limit.", "Automated block executed."]))
        await event.client(BlockRequest(event.sender_id))
        return
        
    if now - last_warn > 30:
        strikes += 1
        await db.execute("INSERT OR REPLACE INTO pm_strikes (user_id, strikes, blocked) VALUES (?, ?, 0)", (event.sender_id, strikes))
        _warn_throttle[event.sender_id] = now
        await event.reply(render("PM GUARD INTERVENTION", [
            "I am currently unavailable.", 
            "Please wait for approval before sending further messages.",
            "---",
            f"Strike {strikes}/3. Further spam will result in a ban."
        ]))
