"""Practical bounded Telegram inspection and message utilities for Program E."""
from __future__ import annotations

import re

from config import config
from core.errors import CommandError
from core.registry import register_cmd
from helpers.entity import resolve_target
from helpers.hud import render

_MAX_BULK = 100
_MAX_REPLY = 4000


async def setup(client):
    p = re.escape(config.PREFIX)
    register_cmd(client, rf"^{p}(msg|inspect)$", handle_inspect, "telegram", "Inspect the replied Telegram message.")
    register_cmd(client, rf"^{p}(id|ref)$", handle_id, "telegram", "Show chat and message IDs.")
    register_cmd(client, rf"^{p}link$", handle_link, "telegram", "Build a message link when Telegram exposes one.")
    register_cmd(client, rf"^{p}entity(?:\s+(.+))?$", handle_entity, "telegram", "Inspect a Telegram entity.")
    register_cmd(client, rf"^{p}chatdiag$", handle_chatdiag, "telegram", "Show bounded chat diagnostics.")
    register_cmd(client, rf"^{p}reply\s+(.+)$", handle_reply, "telegram", "Reply to the current message with bounded text.")
    register_cmd(client, rf"^{p}bulkdel(?:\s+(\d+))?$", handle_bulkdel, "telegram", "Delete a bounded number of recent messages.")


async def handle_inspect(event):
    msg = await event.get_reply_message()
    if msg is None:
        raise CommandError("Reply to a message to inspect it.")
    media = type(msg.media).__name__ if msg.media else "none"
    text = (msg.raw_text or "").replace("\n", " ")[:300]
    await event.edit(render("MESSAGE", [f"ID: `{msg.id}`", f"Sender: `{msg.sender_id}`", f"Date: `{msg.date}`", f"Media: `{media}`", f"Text: {text or '—'}"], footer="telegram | inspect"))


async def handle_id(event):
    msg = await event.get_reply_message()
    lines = [f"Chat: `{event.chat_id}`", f"Command message: `{event.id}`"]
    if msg:
        lines += [f"Reply message: `{msg.id}`", f"Reply sender: `{msg.sender_id}`"]
    await event.edit(render("TELEGRAM IDS", lines, footer="telegram | id"))


async def handle_link(event):
    msg = await event.get_reply_message()
    if msg is None:
        msg = event
    try:
        link = await event.client.get_message_link(msg)
    except Exception as exc:
        raise CommandError(f"Telegram did not expose a message link: {type(exc).__name__}.") from exc
    await event.edit(render("MESSAGE LINK", [link], footer="telegram | link"))


async def handle_reply(event):
    text = event.pattern_match.group(1).strip()
    if len(text) > _MAX_REPLY:
        raise CommandError(f"Reply text must be {_MAX_REPLY} characters or fewer.")
    reply = await event.get_reply_message()
    if reply is None:
        raise CommandError("Reply to a message to use `.reply`.")
    await event.client.send_message(event.chat_id, text, reply_to=reply.id)
    await event.delete()


async def handle_entity(event):
    target = await resolve_target(event)
    name = getattr(target, "title", None) or getattr(target, "first_name", None) or getattr(target, "username", None) or "—"
    username = getattr(target, "username", None) or "—"
    await event.edit(render("ENTITY", [f"ID: `{target.id}`", f"Name: {name}", f"Username: @{username}" if username != "—" else "Username: —", f"Type: `{type(target).__name__}`"], footer="telegram | entity"))


async def handle_chatdiag(event):
    chat = await event.get_chat()
    title = getattr(chat, "title", None) or getattr(chat, "first_name", None) or "Private chat"
    username = getattr(chat, "username", None) or "—"
    participants = getattr(chat, "participants_count", None)
    await event.edit(render("CHAT DIAGNOSTICS", [f"ID: `{event.chat_id}`", f"Title: {title}", f"Username: @{username}" if username != "—" else "Username: —", f"Participants: {participants if participants is not None else 'unknown'}"], footer="telegram | chatdiag"))


async def handle_bulkdel(event):
    raw = event.pattern_match.group(1)
    count = int(raw) if raw else 20
    if not 1 <= count <= _MAX_BULK:
        raise CommandError(f"Bulk delete must be between 1 and {_MAX_BULK} messages.")
    messages = []
    async for msg in event.client.iter_messages(event.chat_id, limit=count + 1):
        if msg.id != event.id:
            messages.append(msg.id)
    if messages:
        await event.client.delete_messages(event.chat_id, messages)
    await event.respond(render("BULK DELETE", [f"Deleted: {len(messages)}", f"Limit: {count}"], footer="telegram | bulkdel"))
