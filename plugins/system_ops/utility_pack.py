from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import re

from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(uuid|sha256|jsonfmt|b64|urlencode|timestamp|head|rss)(?:\s+([\s\S]+))?$"


def _ctx():
    ctx = get_application_context()
    if ctx is None:
        raise CommandError("Runtime context is unavailable")
    return ctx


async def setup(client):
    register_cmd(client, PATTERN, handle, "utilities", "Bounded developer, web and feed utilities using shared services.")


async def handle(event):
    cmd = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip()

    if cmd == "uuid":
        value = str(uuid.uuid4())
    elif cmd == "timestamp":
        value = str(int(time.time()))
    elif not arg:
        raise CommandError(f"Usage: {config.PREFIX}{cmd} <value>")
    elif cmd == "sha256":
        value = hashlib.sha256(arg.encode()).hexdigest()
    elif cmd == "jsonfmt":
        try:
            value = json.dumps(json.loads(arg), indent=2, ensure_ascii=False)[:3500]
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON: {exc.msg}") from exc
    elif cmd == "b64":
        value = base64.b64encode(arg.encode()).decode()
    elif cmd == "urlencode":
        value = urllib.parse.quote_plus(arg)
    elif cmd == "head":
        ctx = _ctx()
        parsed = urllib.parse.urlparse(arg)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CommandError("Only absolute HTTP(S) URLs are accepted")
        response = await ctx.get("http").get(arg, timeout=10, response_limit=64 * 1024, allow_redirects=False)
        value = f"HTTP {response.status}\nContent-Type: {response.headers.get('Content-Type', 'unknown')}\nLength: {response.headers.get('Content-Length', 'unknown')}"
    elif cmd == "rss":
        ctx = _ctx()
        parsed = urllib.parse.urlparse(arg)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CommandError("Only absolute HTTP(S) feed URLs are accepted")
        response = await ctx.get("http").get(arg, timeout=15, response_limit=512 * 1024)
        try:
            root = ET.fromstring(response.body)
        except ET.ParseError as exc:
            raise CommandError("Feed is not valid XML") from exc
        items = []
        for item in root.findall(".//item")[:10]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title:
                items.append(f"{title} — {link}" if link else title)
        if not items:
            for item in root.findall(".//{*}entry")[:10]:
                title = (item.findtext("{*}title") or "").strip()
                if title:
                    items.append(title)
        value = "\n".join(items)[:3500] if items else "No feed entries found."
    else:
        raise CommandError("Unsupported utility")

    await event.edit(render(f"{cmd.upper()} // RESULT", value.splitlines()[:40], footer=f"utilities | {cmd}"))
