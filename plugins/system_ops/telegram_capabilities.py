from __future__ import annotations

import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render

PATTERN = rf"^{re.escape(config.PREFIX)}tgcap(?:\s+(.*))?$"


def _ctx():
    context = get_application_context()
    if context is None:
        raise CommandError("Runtime context is unavailable")
    return context


def _target_label(target) -> str:
    username = getattr(target, "username", None)
    if username:
        return f"@{username}"
    title = getattr(target, "title", None)
    if title:
        return str(title)
    first = getattr(target, "first_name", None)
    last = getattr(target, "last_name", None)
    name = " ".join(part for part in (first, last) if part)
    if name:
        return name
    entity_id = getattr(target, "id", None)
    return str(entity_id) if entity_id is not None else str(target)


def _fmt(value) -> str:
    if value is True:
        return "YES"
    if value is False:
        return "NO"
    if value is None:
        return "UNKNOWN"
    return str(value).upper()


async def handle(event):
    ctx = _ctx()
    arg = (event.pattern_match.group(1) or "").strip()
    telegram = ctx.get("telegram")

    if arg:
        target = await telegram.get_entity(arg)
    else:
        reply = await event.get_reply_message()
        target = reply.chat if reply is not None and getattr(reply, "chat", None) is not None else event.chat_id

    capabilities = await telegram.get_capabilities(target)
    observed_at = capabilities.get("observed_at")
    target_label = _target_label(target)
    rows = [
        f"Target        {target_label}",
        f"Observed      {observed_at:.0f}" if isinstance(observed_at, (int, float)) else "Observed      UNKNOWN",
        "",
        f"Can read      {_fmt(capabilities.get('can_read'))}",
        f"Can send      {_fmt(capabilities.get('can_send'))}",
        f"Can edit      {_fmt(capabilities.get('can_edit'))}",
        f"Can delete    {_fmt(capabilities.get('can_delete'))}",
        f"Can pin       {_fmt(capabilities.get('can_pin'))}",
        f"Can react     {_fmt(capabilities.get('can_react'))}",
        f"Slow mode     {_fmt(capabilities.get('slow_mode_seconds'))}",
        f"Restricted    {_fmt(capabilities.get('restricted'))}",
    ]
    if capabilities.get("permissions_observation"):
        rows += ["", f"Permissions   {capabilities['permissions_observation']}"]
    rows += ["", "OBSERVATION ONLY · NOT MUTATION AUTHORITY"]
    await event.edit(render("TELEGRAM // CAPABILITIES", rows, footer="system_ops | tgcap | observed state"))


async def setup(client):
    register_cmd(client, PATTERN, handle, "system_ops", "Observe Telegram peer capabilities without treating cache state as authority.")
