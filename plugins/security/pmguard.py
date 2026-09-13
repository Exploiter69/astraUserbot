import asyncio
import re
import time
from telethon import events
from telethon.tl.functions.contacts import GetContactsRequest, BlockRequest
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from helpers.entity import resolve_target
from config import config

db = Database.get("pmguard")
PATTERN = rf"^{re.escape(config.PREFIX)}(pmpermit|allow|approve|disallow|disapprove|listallowed|listdisallowed)(?:\s+(.*))?$"
_warn_throttle: dict[int, float] = {}
_cached_contacts: set[int] = set()
_last_contact_refresh = 0.0
_CONTACT_REFRESH_SECONDS = 300
_MAX_LIST = 100
_MAX_THROTTLE_ENTRIES = 4096
_state_lock = asyncio.Lock()


async def _refresh_contacts(client, *, force=False):
    global _last_contact_refresh
    now = time.monotonic()
    if not force and now - _last_contact_refresh < _CONTACT_REFRESH_SECONDS:
        return
    try:
        contacts = await client(GetContactsRequest(hash=0))
        _cached_contacts.clear()
        _cached_contacts.update(contact.id for contact in contacts.users)
        _last_contact_refresh = now
    except Exception:
        return


async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS pm_settings (id INTEGER PRIMARY KEY CHECK (id=1), enabled INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pm_whitelist (user_id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS pm_strikes (user_id INTEGER PRIMARY KEY, strikes INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0);
        INSERT OR IGNORE INTO pm_settings (id, enabled) VALUES (1, 0);
    """)
    register_cmd(client, PATTERN, handle_pmguard, "security", "PM Guard Gatekeeper.")
    client.add_event_handler(pm_watcher, events.NewMessage(incoming=True, func=lambda e: e.is_private))
    await _refresh_contacts(client, force=True)


async def handle_pmguard(event):
    cmd = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip()
    if cmd == "pmpermit":
        if arg.lower() not in {"", "on", "off"}:
            raise CommandError("Usage: .pmpermit [on|off]")
        state = 1 if arg.lower() == "on" else 0
        await db.execute("UPDATE pm_settings SET enabled = ? WHERE id = 1", (state,))
        await event.edit(render("PM GUARD", [f"Status: {'ENABLED' if state else 'DISABLED'}"]))
        return
    if cmd in ("listallowed", "listdisallowed"):
        table = "pm_whitelist" if cmd == "listallowed" else "pm_strikes WHERE blocked = 1"
        rows = await db.fetchall(f"SELECT user_id FROM {table} LIMIT ?", (_MAX_LIST,))
        text_rows = [f"- {r[0]}" for r in rows] if rows else ["No records found."]
        await event.edit(render(cmd.upper(), text_rows))
        return
    if cmd not in {"allow", "approve", "disallow", "disapprove"}:
        raise CommandError("Unknown PM Guard command.")
    target = await resolve_target(event)
    if target.id == config.OWNER_ID:
        raise CommandError("Cannot modify the owner authorization.")
    if cmd in ("allow", "approve"):
        await db.execute("INSERT OR REPLACE INTO pm_whitelist (user_id) VALUES (?)", (target.id,))
        await db.execute("DELETE FROM pm_strikes WHERE user_id = ?", (target.id,))
        await event.edit(render("PM GUARD", [f"User {target.id} whitelisted."]))
    else:
        await db.execute("DELETE FROM pm_whitelist WHERE user_id = ?", (target.id,))
        await db.execute("DELETE FROM pm_strikes WHERE user_id = ?", (target.id,))
        await event.edit(render("PM GUARD", [f"User {target.id} authorization revoked."]))


def _remember_warning(user_id: int, now: float) -> None:
    _warn_throttle[user_id] = now
    if len(_warn_throttle) > _MAX_THROTTLE_ENTRIES:
        oldest = sorted(_warn_throttle.items(), key=lambda item: item[1])[: len(_warn_throttle) - _MAX_THROTTLE_ENTRIES]
        for key, _ in oldest:
            _warn_throttle.pop(key, None)


async def pm_watcher(event):
    if not event.is_private or event.sender_id == config.OWNER_ID:
        return
    await _refresh_contacts(event.client)
    if event.sender_id in _cached_contacts:
        return
    status = await db.fetchone("SELECT enabled FROM pm_settings WHERE id = 1")
    if not status or status[0] == 0:
        return
    wl = await db.fetchone("SELECT user_id FROM pm_whitelist WHERE user_id = ?", (event.sender_id,))
    if wl:
        return

    async with _state_lock:
        strike_data = await db.fetchone("SELECT strikes, blocked FROM pm_strikes WHERE user_id = ?", (event.sender_id,))
        strikes = strike_data[0] if strike_data else 0
        blocked = strike_data[1] if strike_data else 0
        if blocked:
            return
        now = time.time()
        last_warn = _warn_throttle.get(event.sender_id, 0)
        if strikes >= 3:
            await db.execute("UPDATE pm_strikes SET strikes = 4, blocked = 1 WHERE user_id = ?", (event.sender_id,))
            should_block = True
        elif now - last_warn > 30:
            strikes += 1
            await db.execute("INSERT OR REPLACE INTO pm_strikes (user_id, strikes, blocked) VALUES (?, ?, 0)", (event.sender_id, strikes))
            _remember_warning(event.sender_id, now)
            should_block = False
        else:
            return

    if should_block:
        await event.reply(render("PM GUARD: BLOCKED", ["You have exceeded the warning limit.", "Automated block executed."]))
        try:
            await event.client(BlockRequest(event.sender_id))
        except Exception:
            return
        return

    await event.reply(render("PM GUARD INTERVENTION", ["I am currently unavailable.", "Please wait for approval before sending further messages.", "---", f"Strike {strikes}/3. Further spam will result in a ban."]))
