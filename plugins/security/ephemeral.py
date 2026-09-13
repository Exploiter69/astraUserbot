import re

from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}savevo$"

async def setup(client):
    register_cmd(client, PATTERN, handle_savevo, "security", "Save View-Once media without triggering destruction.")

async def handle_savevo(event):
    if not event.is_reply:
        raise CommandError("Reply to a view-once media message.")
    reply = await event.get_reply_message()
    if not reply.media or getattr(reply.media, "ttl_seconds", None) is None:
        raise CommandError("Replied message is not a View-Once (TTL) media.")

    context = get_application_context()
    if context is None:
        raise CommandError("Required runtime services are unavailable.")
    media_service = context.get("media")
    if media_service is None:
        raise CommandError("Required runtime services are unavailable.")

    await event.edit(render("EPHEMERAL BYPASS", ["Intercepting payload..."], footer="security | ephemeral"))
    workspace = await media_service.create_workspace("view-once")
    downloaded = None
    try:
        downloaded = await media_service.download_telegram_media(
            event.client.download_media,
            reply.media,
            workspace=workspace,
        )
        if not downloaded:
            raise CommandError("Failed to intercept payload.")
        artifact = media_service.artifact(workspace, downloaded)
        await event.client.send_file("me", file=artifact.path, caption="Intercepted View-Once Media")
        await event.edit(render("EPHEMERAL BYPASS", ["Payload secured in Saved Messages."], footer="security | ephemeral"))
    finally:
        await media_service.cleanup(workspace)
