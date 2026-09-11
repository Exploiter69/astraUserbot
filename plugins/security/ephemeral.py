import os
import re
import uuid
from pathlib import Path
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}savevo$"
_MAX_MEDIA_BYTES = 512 * 1024 * 1024

async def setup(client):
    register_cmd(client, PATTERN, handle_savevo, "security", "Save View-Once media without triggering destruction.")

async def handle_savevo(event):
    if not event.is_reply:
        raise CommandError("Reply to a view-once media message.")
    reply = await event.get_reply_message()
    if not reply.media or getattr(reply.media, "ttl_seconds", None) is None:
        raise CommandError("Replied message is not a View-Once (TTL) media.")

    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / f"vo_{uuid.uuid4().hex}"
    await event.edit(render("EPHEMERAL BYPASS", ["Intercepting payload..."]))
    downloaded = await event.client.download_media(reply.media, file=file_path)
    if not downloaded or not os.path.exists(downloaded):
        raise CommandError("Failed to intercept payload.")
    try:
        size = os.path.getsize(downloaded)
        if size > _MAX_MEDIA_BYTES:
            raise CommandError("View-Once media exceeds the 512 MiB safety limit.")
        await event.client.send_file("me", file=downloaded, caption="Intercepted View-Once Media")
        await event.edit(render("EPHEMERAL BYPASS", ["Payload secured in Saved Messages."]))
    finally:
        try:
            if os.path.exists(downloaded):
                os.remove(downloaded)
        except OSError:
            pass
