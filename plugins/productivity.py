"""Durable owner productivity helpers for Program E."""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

from core.database import Database
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

DB = Database.get("productivity")
_MAX_TEXT = 4000
_MAX_NAME = 48
_MAX_ROWS = 100


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
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            reply_to INTEGER,
            text TEXT NOT NULL,
            due_at REAL NOT NULL,
            delivered INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(delivered, due_at);
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(chat_id, message_id, tag)
        );
        CREATE TABLE IF NOT EXISTS templates (
            name TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
    """)
    register_cmd(client, rf"^{re.escape(config.PREFIX)}remind\s+(\S+)\s+(.+)$", handle_remind, "productivity", "Set a durable reminder.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}reminders$", handle_reminders, "productivity", "List pending reminders.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}delremind\s+(\d+)$", handle_delremind, "productivity", "Delete a reminder.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}bookmark(?:\s+(\S+))?$", handle_bookmark, "productivity", "Bookmark a replied message.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}bookmarks$", handle_bookmarks, "productivity", "List saved bookmarks.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}unbookmark\s+(\d+)$", handle_unbookmark, "productivity", "Delete a bookmark.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}template\s+(\S+)\s+(.+)$", handle_template, "productivity", "Create or update a reusable template.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}tget\s+(\S+)$", handle_tget, "productivity", "Render a reusable template.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}tlist$", handle_tlist, "productivity", "List reusable templates.")
    register_cmd(client, rf"^{re.escape(config.PREFIX)}tdel\s+(\S+)$", handle_tdel, "productivity", "Delete a reusable template.")
    client.loop.create_task(_reminder_worker(client))


async def handle_remind(event):
    seconds = _parse_delay(event.pattern_match.group(1))
    text = _clean(event.pattern_match.group(2), _MAX_TEXT)
    due = time.time() + seconds
    row = await DB.execute_returning_id(
        "INSERT INTO reminders(chat_id, reply_to, text, due_at, created_at) VALUES(?,?,?,?,?)",
        (event.chat_id, event.id, text, due, time.time()),
    )
    await event.edit(render("REMINDER SET", [f"ID: `{row}`", f"Due: {datetime.fromtimestamp(due, timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}", f"Text: {text}"], footer="productivity | reminder"))


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


async def _reminder_worker(client):
    while True:
        try:
            rows = await DB.fetchall("SELECT id, chat_id, reply_to, text FROM reminders WHERE delivered=0 AND due_at <= ? ORDER BY due_at LIMIT 20", (time.time(),))
            for rid, chat_id, reply_to, text in rows:
                try:
                    await client.send_message(chat_id, render("REMINDER", [text], footer="productivity | reminder"), reply_to=reply_to)
                    await DB.execute("UPDATE reminders SET delivered=1 WHERE id=? AND delivered=0", (rid,))
                except Exception:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(2)
