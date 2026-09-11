import logging
import os
import re
import time

from telethon import events
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from helpers.entity import resolve_target
from config import config

logger = logging.getLogger("astra.plugins.account_archiver")
db = Database.get("account_archiver")
PATTERN_ARCH = rf"^{re.escape(config.PREFIX)}arch(?:\s+(status|stats|search))?(?:\s+(.*))?$"
PATTERN_TRACK = rf"^{re.escape(config.PREFIX)}track(?:\s+(add|remove|list))?(?:\s+(.*))?$"

_RETENTION_DAYS = max(1, int(os.getenv("ASTRA_ARCHIVE_RETENTION_DAYS", "30")))
_MAX_MESSAGES = max(1000, int(os.getenv("ASTRA_ARCHIVE_MAX_MESSAGES", "100000")))
_CLEANUP_INTERVAL = 300.0
_MAX_SEARCH = 128
_MAX_DISPLAY = 100
_last_cleanup = 0.0

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS arch_settings (key TEXT PRIMARY KEY, val INTEGER);
        INSERT OR IGNORE INTO arch_settings (key, val) VALUES ('enabled', 0);
        CREATE TABLE IF NOT EXISTS group_watchlist (chat_id INTEGER, user_id INTEGER, PRIMARY KEY (chat_id, user_id));
        CREATE TABLE IF NOT EXISTS user_accounts (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
            is_bot INTEGER, is_verified INTEGER, first_seen REAL, last_seen REAL
        );
        CREATE TABLE IF NOT EXISTS account_messages (
            message_id INTEGER, chat_id INTEGER, user_id INTEGER, text TEXT,
            media_type TEXT, timestamp REAL, PRIMARY KEY (message_id, chat_id)
        );
        CREATE INDEX IF NOT EXISTS idx_account_messages_timestamp ON account_messages(timestamp);
        CREATE INDEX IF NOT EXISTS idx_account_messages_user ON account_messages(user_id);
    """)
    register_cmd(client, PATTERN_ARCH, handle_arch, "security", "Account DM and watchlist archiver with bounded retention.")
    register_cmd(client, PATTERN_TRACK, handle_track, "security", "Manage group archiving watchlist.")
    client.add_event_handler(archive_watcher, events.NewMessage(incoming=True))

async def _cleanup_if_due(now: float) -> None:
    global _last_cleanup
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    cutoff = now - (_RETENTION_DAYS * 86400)
    try:
        await db.execute("DELETE FROM account_messages WHERE timestamp < ?", (cutoff,))
        await db.execute(
            "DELETE FROM account_messages WHERE rowid IN (SELECT rowid FROM account_messages ORDER BY timestamp DESC LIMIT -1 OFFSET ?)",
            (_MAX_MESSAGES,),
        )
        await db.execute(
            "DELETE FROM user_accounts WHERE NOT EXISTS (SELECT 1 FROM account_messages m WHERE m.user_id = user_accounts.user_id)"
            " AND NOT EXISTS (SELECT 1 FROM group_watchlist w WHERE w.user_id = user_accounts.user_id)"
        )
    except Exception:
        logger.exception("Account archive retention cleanup failed")

async def handle_arch(event):
    cmd = (event.pattern_match.group(1) or "").lower()
    arg = (event.pattern_match.group(2) or "").strip()
    if cmd == "status":
        if arg:
            if arg.lower() not in {"on", "off", "1", "0", "true", "false", "enable", "disable"}:
                raise CommandError("Usage: .arch status [on|off]")
            state = 1 if arg.lower() in ("on", "1", "true", "enable") else 0
            await db.execute("UPDATE arch_settings SET val = ? WHERE key = 'enabled'", (state,))
        row = await db.fetchone("SELECT val FROM arch_settings WHERE key = 'enabled'")
        current_state = row[0] if row else 0
        await event.edit(render("ARCHIVER STATUS", [f"Global Archiving: {'ENABLED' if current_state else 'DISABLED'}"]))
    elif cmd == "stats":
        if arg:
            raise CommandError("Usage: .arch stats")
        users_count = await db.fetchone("SELECT COUNT(*) FROM user_accounts")
        msg_count = await db.fetchone("SELECT COUNT(*) FROM account_messages")
        await event.edit(render("ARCHIVER STATS", [f"Unique Accounts Tracked: {users_count[0]}", f"Total Messages Logged: {msg_count[0]}"], footer="security | archiver"))
    elif cmd == "search":
        if not arg:
            raise CommandError("Please provide a keyword to search.")
        if len(arg) > _MAX_SEARCH:
            raise CommandError(f"Search keyword must be {_MAX_SEARCH} characters or fewer.")
        rows = await db.fetchall(
            "SELECT u.username, u.first_name, m.text FROM account_messages m JOIN user_accounts u ON m.user_id = u.user_id "
            "WHERE m.text LIKE ? ORDER BY m.timestamp DESC LIMIT 10", (f"%{arg}%",)
        )
        if not rows:
            raise CommandError(f"No results found for '{arg}'.")
        display_rows = ["Search Results:", "---"]
        for username, first_name, text in rows:
            name_display = username or first_name or "unknown"
            content = (text or "")[:45]
            if len(text or "") > 45:
                content += "..."
            display_rows.append(f"[{name_display}]: {content}")
        await event.edit(render("ARCHIVER SEARCH", display_rows, footer="security | archiver"))
    else:
        raise CommandError("Usage: .arch status [on/off] | .arch stats | .arch search <keyword>")

async def handle_track(event):
    cmd = (event.pattern_match.group(1) or "").lower()
    if cmd == "list":
        rows = await db.fetchall("SELECT user_id FROM group_watchlist WHERE chat_id = ?", (event.chat_id,))
        display = [f"- {row[0]}" for row in rows[:_MAX_DISPLAY]] if rows else ["No users are tracked in this group."]
        if len(rows) > _MAX_DISPLAY:
            display.append(f"... and {len(rows) - _MAX_DISPLAY} more")
        await event.edit(render(f"WATCHLIST: {event.chat_id}", display))
        return
    if cmd not in {"add", "remove"}:
        raise CommandError("Usage: .track add | remove | list")
    target = await resolve_target(event)
    if cmd == "add":
        await db.execute("INSERT OR IGNORE INTO group_watchlist (chat_id, user_id) VALUES (?, ?)", (event.chat_id, target.id))
        await event.edit(render("WATCHLIST UPDATED", [f"Now tracking {target.id} in this group."]))
    else:
        await db.execute("DELETE FROM group_watchlist WHERE chat_id = ? AND user_id = ?", (event.chat_id, target.id))
        await event.edit(render("WATCHLIST UPDATED", [f"Stopped tracking {target.id} in this group."]))

async def archive_watcher(event):
    if not event.sender_id:
        return
    status = await db.fetchone("SELECT val FROM arch_settings WHERE key = 'enabled'")
    if not status or status[0] == 0:
        return
    should_log = event.is_private
    if event.is_group or event.is_channel:
        row = await db.fetchone("SELECT 1 FROM group_watchlist WHERE chat_id = ? AND user_id = ?", (event.chat_id, event.sender_id))
        should_log = bool(row)
    if not should_log:
        return
    try:
        sender = await event.get_sender()
        now = time.time()
        await db.execute(
            "INSERT INTO user_accounts (user_id, username, first_name, last_name, is_bot, is_verified, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, "
            "last_name=excluded.last_name, last_seen=excluded.last_seen",
            (event.sender_id, getattr(sender, "username", None), getattr(sender, "first_name", None), getattr(sender, "last_name", None),
             1 if getattr(sender, "bot", False) else 0, 1 if getattr(sender, "verified", False) else 0, now, now),
        )
        media_type = type(event.media).__name__ if event.media else None
        await db.execute(
            "INSERT OR IGNORE INTO account_messages (message_id, chat_id, user_id, text, media_type, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (event.id, event.chat_id, event.sender_id, event.text or "", media_type, now),
        )
        await _cleanup_if_due(now)
    except Exception:
        logger.exception("Account archive write failed")
