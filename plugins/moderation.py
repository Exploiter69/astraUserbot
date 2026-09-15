"""Bounded, owner-controlled group moderation helpers for Program E."""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.functions.messages import UpdatePinnedMessageRequest
from telethon.tl.types import ChatBannedRights

from config import config
from core.database import Database
from core.errors import CommandError
from core.registry import register_cmd
from helpers.entity import resolve_target
from helpers.hud import render

DB = Database.get("moderation")
_MAX_AUDIT = 5000
_MAX_LOCKDOWN = 200
_SPAM_WINDOW = 20.0
_SPAM_LIMIT = 6
_recent: dict[int, deque[float]] = defaultdict(deque)


def _reason(raw: str) -> str:
    value = raw.strip()
    if len(value) > 500:
        raise CommandError("Reason must be 500 characters or fewer.")
    return value or "No reason provided"


async def setup(client):
    await DB.init_schema("""
        CREATE TABLE IF NOT EXISTS moderation_warnings (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            last_reason TEXT,
            updated_at REAL NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS moderation_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_id INTEGER,
            actor_id INTEGER,
            reason TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mod_audit_chat ON moderation_audit(chat_id, created_at DESC);
    """)
    pattern = rf"^{re.escape(config.PREFIX)}(warn|warnings|mute|unmute|ban|unban|pin|unpin|lockdown|modreport)(?:\s+(.*))?$"
    register_cmd(client, pattern, handle_moderation, "moderation", "Bounded owner-controlled group moderation.")


async def _audit(chat_id, action, target_id, reason):
    await DB.execute("INSERT INTO moderation_audit(chat_id,action,target_id,actor_id,reason,created_at) VALUES(?,?,?,?,?,?)", (chat_id, action, target_id, config.OWNER_ID, reason[:500], time.time()))


async def handle_moderation(event):
    cmd = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip()
    if cmd == "modreport":
        rows = await DB.fetchall("SELECT action,target_id,reason,created_at FROM moderation_audit WHERE chat_id=? ORDER BY id DESC LIMIT ?", (event.chat_id, _MAX_AUDIT))
        lines = [f"{action} · `{target}` · {reason[:100]}" for action, target, reason, _ in rows]
        await event.edit(render("MODERATION AUDIT", lines or ["No moderation actions recorded."], footer="moderation | audit"))
        return

    if cmd == "lockdown":
        if arg.upper() != "CONFIRM":
            raise CommandError("Lockdown is destructive. Use `.lockdown CONFIRM`.")
        count = 0
        async for user in event.client.iter_participants(event.chat_id, limit=_MAX_LOCKDOWN):
            if getattr(user, "bot", False) or user.id == config.OWNER_ID:
                continue
            try:
                await event.client(EditBannedRequest(event.chat_id, user.id, ChatBannedRights(until_date=None, send_messages=True)))
                count += 1
            except Exception:
                continue
        await _audit(event.chat_id, "LOCKDOWN", None, f"bounded participants={count}")
        await event.edit(render("LOCKDOWN", [f"Restricted {count} participants (bounded at {_MAX_LOCKDOWN})."], footer="moderation | lockdown"))
        return

    target = await resolve_target(event)
    if target.id == config.OWNER_ID and cmd in {"mute", "ban", "warn"}:
        raise CommandError("Cannot moderate the owner account.")
    reason = _reason(arg)

    if cmd == "warn":
        row = await DB.fetchone("SELECT count FROM moderation_warnings WHERE chat_id=? AND user_id=?", (event.chat_id, target.id))
        count = int(row[0]) + 1 if row else 1
        await DB.execute("INSERT INTO moderation_warnings(chat_id,user_id,count,last_reason,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET count=excluded.count,last_reason=excluded.last_reason,updated_at=excluded.updated_at", (event.chat_id, target.id, count, reason, time.time()))
        await _audit(event.chat_id, "WARN", target.id, reason)
        await event.edit(render("WARNING", [f"Target: `{target.id}`", f"Warnings: {count}", f"Reason: {reason}"], footer="moderation | warn"))
    elif cmd == "warnings":
        row = await DB.fetchone("SELECT count,last_reason FROM moderation_warnings WHERE chat_id=? AND user_id=?", (event.chat_id, target.id))
        await event.edit(render("WARNINGS", [f"Target: `{target.id}`", f"Count: {row[0] if row else 0}", f"Last reason: {(row[1] if row else '—')}"], footer="moderation | warnings"))
    elif cmd in {"mute", "unmute", "ban", "unban"}:
        rights = ChatBannedRights(until_date=None, send_messages=cmd == "mute", view_messages=cmd == "ban")
        await event.client(EditBannedRequest(event.chat_id, target.id, rights))
        await _audit(event.chat_id, cmd.upper(), target.id, reason)
        await event.edit(render("MODERATION", [f"Action: {cmd.upper()}", f"Target: `{target.id}`"], footer="moderation | action"))
    elif cmd in {"pin", "unpin"}:
        reply = await event.get_reply_message()
        if reply is None:
            raise CommandError("Reply to the message to pin or unpin.")
        await event.client(UpdatePinnedMessageRequest(event.chat_id, reply.id, silent=True, unpin=(cmd == "unpin")))
        await _audit(event.chat_id, cmd.upper(), reply.id, reason)
        await event.edit(render("PIN", [f"Action: {cmd.upper()}", f"Message: `{reply.id}`"], footer="moderation | pin"))
