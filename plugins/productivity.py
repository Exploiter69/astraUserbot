"""Durable owner productivity helpers for Program E."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone

from telethon import events
from core.context import get_application_context
from core.database import Database
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

logger = logging.getLogger("astra.productivity")
DB = Database.get("productivity")
_MAX_TEXT = 4000
_MAX_NAME = 48
_MAX_ROWS = 100
_FILTER_COOLDOWN = 60.0
_REMINDER_BATCH = 20
_filter_last: OrderedDict[tuple[int, str], float] = OrderedDict()


def _parse_delay(value: str) -> int:
    m = re.fullmatch(r"(\d{1,6})([smhd])", value.lower())
    if not m:
        raise CommandError("Reminder delay must look like 30s, 10m, 2h or 1d.")
    amount, unit = int(m.group(1)), m.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    if not 5 <= seconds <= 30 * 86400:
        raise CommandError("Reminder delay must be between 5 seconds and 30 days.")
    return seconds


def _clean(value: str, limit: int) -> str:
    value = value.strip()
    if not value or len(value) > limit:
        raise CommandError(f"Value must be 1-{limit} characters.")
    return value


async def setup(client):
    await DB.init_schema("""
        CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, reply_to INTEGER, text TEXT NOT NULL, due_at REAL NOT NULL, delivered INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(delivered, due_at);
        CREATE TABLE IF NOT EXISTS bookmarks (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, tag TEXT NOT NULL, text TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(chat_id, message_id, tag));
        CREATE TABLE IF NOT EXISTS templates (name TEXT PRIMARY KEY, text TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS filters (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, term TEXT NOT NULL, response TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, UNIQUE(chat_id, term));
    """)
    p = re.escape(config.PREFIX)
    register_cmd(client, rf"^{p}remind\s+(\S+)\s+(.+)$", handle_remind, "productivity", "Set a durable reminder.")
    register_cmd(client, rf"^{p}reminders$", handle_reminders, "productivity", "List pending reminders.")
    register_cmd(client, rf"^{p}delremind\s+(\d+)$", handle_delremind, "productivity", "Delete a reminder.")
    register_cmd(client, rf"^{p}bookmark(?:\s+(\S+))?$", handle_bookmark, "productivity", "Bookmark a replied message.")
    register_cmd(client, rf"^{p}bookmarks$", handle_bookmarks, "productivity", "List saved bookmarks.")
    register_cmd(client, rf"^{p}unbookmark\s+(\d+)$", handle_unbookmark, "productivity", "Delete a bookmark.")
    register_cmd(client, rf"^{p}template\s+(\S+)\s+(.+)$", handle_template, "productivity", "Create or update a reusable template.")
    register_cmd(client, rf"^{p}tget\s+(\S+)$", handle_tget, "productivity", "Render a reusable template.")
    register_cmd(client, rf"^{p}tlist$", handle_tlist, "productivity", "List reusable templates.")
    register_cmd(client, rf"^{p}tdel\s+(\S+)$", handle_tdel, "productivity", "Delete a reusable template.")
    register_cmd(client, rf"^{p}filter\s+add\s+(\S+)\s+(.+)$", handle_filter_add, "productivity", "Add a bounded keyword auto-response filter.")
    register_cmd(client, rf"^{p}filter\s+(?:del|delete)\s+(\d+)$", handle_filter_del, "productivity", "Delete a filter.")
    register_cmd(client, rf"^{p}filter\s+list$", handle_filter_list, "productivity", "List filters.")
    client.add_event_handler(filter_watcher, events.NewMessage(incoming=True))

    context = get_application_context()
    if context is not None:
        context.tasks.create_task(_reminder_worker(context.get("telegram")), name="productivity.reminder_worker", owner="productivity")
    else:
        logger.warning("ApplicationContext unavailable; starting unmanaged reminder worker")
        client.loop.create_task(_reminder_worker(client))


async def handle_remind(event):
    seconds = _parse_delay(event.pattern_match.group(1))
    text = _clean(event.pattern_match.group(2), _MAX_TEXT)
    due = time.time() + seconds
    cursor = await DB.execute("INSERT INTO reminders(chat_id, reply_to, text, due_at, created_at) VALUES(?,?,?,?,?)", (event.chat_id, event.id, text, due, time.time()))
    reminder_id = int(cursor.lastrowid)
    await event.edit(render("REMINDER SET", [f"ID: `{reminder_id}`", f"Due: {datetime.fromtimestamp(due, timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}", f"Text: {text}"], footer="productivity | reminder"))


async def handle_reminders(event):
    rows = await DB.fetchall("SELECT id, due_at, text FROM reminders WHERE delivered=0 ORDER BY due_at LIMIT ?", (_MAX_ROWS,))
    lines = [f"`{r[0]}` · {datetime.fromtimestamp(r[1]).strftime('%Y-%m-%d %H:%M')} · {r[2][:160]}" for r in rows]
    await event.edit(render("REMINDERS", lines or ["No pending reminders."], footer="productivity | reminders"))


async def handle_delremind(event):
    rid = int(event.pattern_match.group(1))
    await DB.execute("DELETE FROM reminders WHERE id=? AND delivered=0", (rid,))
    await event.edit(render("REMINDER", [f"Removed reminder `{rid}`."], footer="productivity | reminder"))


async def handle_bookmark(event):
    reply = await event.get_reply_message()
    if reply is None:
        raise CommandError("Reply to the message you want to bookmark.")
    tag = _clean(event.pattern_match.group(1) or f"msg-{reply.id}", _MAX_NAME)
    text = (reply.raw_text or "[media]").strip()[:_MAX_TEXT]
    await DB.execute("INSERT OR REPLACE INTO bookmarks(chat_id,message_id,tag,text,created_at) VALUES(?,?,?,?,?)", (event.chat_id, reply.id, tag, text, time.time()))
    await event.edit(render("BOOKMARK SAVED", [f"ID: `{reply.id}`", f"Tag: `{tag}`"], footer="productivity | bookmark"))


async def handle_bookmarks(event):
    rows = await DB.fetchall("SELECT id, tag, message_id, text FROM bookmarks ORDER BY created_at DESC LIMIT ?", (_MAX_ROWS,))
    lines = [f"`{r[0]}` · `{r[1]}` · msg {r[2]} · {r[3][:120]}" for r in rows]
    await event.edit(render("BOOKMARKS", lines or ["No bookmarks."], footer="productivity | bookmarks"))


async def handle_unbookmark(event):
    await DB.execute("DELETE FROM bookmarks WHERE id=?", (int(event.pattern_match.group(1)),))
    await event.edit(render("BOOKMARK", ["Bookmark removed."], footer="productivity | bookmark"))


async def handle_template(event):
    name = _clean(event.pattern_match.group(1), _MAX_NAME)
    text = _clean(event.pattern_match.group(2), _MAX_TEXT)
    now = time.time()
    await DB.execute("INSERT INTO templates(name,text,created_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET text=excluded.text, updated_at=excluded.updated_at", (name, text, now, now))
    await event.edit(render("TEMPLATE SAVED", [f"Name: `{name}`"], footer="productivity | template"))


async def handle_tget(event):
    name = _clean(event.pattern_match.group(1), _MAX_NAME)
    row = await DB.fetchone("SELECT text FROM templates WHERE name=?", (name,))
    if not row:
        raise CommandError("Template not found.")
    await event.edit(row[0])


async def handle_tlist(event):
    rows = await DB.fetchall("SELECT name, text FROM templates ORDER BY name LIMIT ?", (_MAX_ROWS,))
    lines = [f"`{r[0]}` · {r[1][:140]}" for r in rows]
    await event.edit(render("TEMPLATES", lines or ["No templates."], footer="productivity | templates"))


async def handle_tdel(event):
    name = _clean(event.pattern_match.group(1), _MAX_NAME)
    await DB.execute("DELETE FROM templates WHERE name=?", (name,))
    await event.edit(render("TEMPLATE", [f"Deleted `{name}`."], footer="productivity | template"))


async def handle_filter_add(event):
    term = _clean(event.pattern_match.group(1).lower(), 128)
    response = _clean(event.pattern_match.group(2), 1000)
    await DB.execute("INSERT INTO filters(chat_id,term,response,created_at) VALUES(?,?,?,?) ON CONFLICT(chat_id,term) DO UPDATE SET response=excluded.response, enabled=1", (event.chat_id, term, response, time.time()))
    await event.edit(render("FILTER SAVED", [f"Term: `{term}`", "Action: bounded auto-response", "Cooldown: 60s per sender"], footer="productivity | filter"))


async def handle_filter_del(event):
    await DB.execute("DELETE FROM filters WHERE chat_id=? AND id=?", (event.chat_id, int(event.pattern_match.group(1))))
    await event.edit(render("FILTER", ["Filter removed."], footer="productivity | filter"))


async def handle_filter_list(event):
    rows = await DB.fetchall("SELECT id, term, response, enabled FROM filters WHERE chat_id=? ORDER BY id LIMIT ?", (event.chat_id, _MAX_ROWS))
    lines = [f"`{r[0]}` · `{r[1]}` · {'ON' if r[3] else 'OFF'} · {r[2][:100]}" for r in rows]
    await event.edit(render("FILTERS", lines or ["No filters in this chat."], footer="productivity | filters"))


async def filter_watcher(event):
    if not event.chat_id or not event.raw_text or event.sender_id == config.OWNER_ID:
        return
    rows = await DB.fetchall("SELECT term, response FROM filters WHERE chat_id=? AND enabled=1 LIMIT ?", (event.chat_id, _MAX_ROWS))
    now = time.time()
    lowered = event.raw_text.lower()
    for term, response in rows:
        if term not in lowered:
            continue
        key = (int(event.sender_id), term)
        previous = _filter_last.get(key, 0.0)
        if now - previous < _FILTER_COOLDOWN:
            continue
        _filter_last[key] = now
        _filter_last.move_to_end(key)
        while len(_filter_last) > 2048:
            _filter_last.popitem(last=False)
        await event.reply(response)
        break


async def _deliver_due_reminders(sender, *, now: float | None = None) -> int:
    """Deliver one bounded batch; failed sends remain pending for retry."""
    current = time.time() if now is None else now
    rows = await DB.fetchall("SELECT id, chat_id, reply_to, text FROM reminders WHERE delivered=0 AND due_at <= ? ORDER BY due_at LIMIT ?", (current, _REMINDER_BATCH))
    delivered = 0
    for rid, chat_id, reply_to, text in rows:
        try:
            await sender.send_message(chat_id, render("REMINDER", [text], footer="productivity | reminder"), reply_to=reply_to)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Reminder delivery failed id=%s chat_id=%s; will retry", rid, chat_id, exc_info=True)
            continue
        try:
            await DB.execute("UPDATE reminders SET delivered=1 WHERE id=? AND delivered=0", (rid,))
            delivered += 1
        except Exception:
            logger.error("Reminder delivery record failed id=%s; it may be retried", rid, exc_info=True)
    return delivered


async def _reminder_worker(sender):
    """Poll durable reminders with bounded work and supervised lifecycle."""
    while True:
        try:
            await _deliver_due_reminders(sender)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("Reminder worker iteration failed; continuing", exc_info=True)
        await asyncio.sleep(2)
