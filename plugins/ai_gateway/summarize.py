import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render

PATTERN = rf"^{re.escape(config.PREFIX)}summarize$"


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_summarize,
        category="ai",
        description="Summarize a replied text message with the configured AI provider.",
    )


async def handle_summarize(event):
    if not event.is_reply:
        raise CommandError("Please reply to a text message to summarize it.")
    reply_msg = await event.get_reply_message()
    text_to_summarize = reply_msg.text
    if not text_to_summarize:
        raise CommandError("The replied message does not contain any text.")

    context = get_application_context()
    if context is None:
        raise CommandError("AI service is unavailable.")
    service = context.get("ai")

    await event.edit(render(
        title="AI SUMMARIZATION",
        rows=["Analyzing text..."],
        footer="ai | summarize",
    ))
    response = await service.summarize(text_to_summarize)
    await event.edit(render(
        title="SUMMARY",
        rows=["---"] + response.text.split("\n"),
        footer=f"ai | summarize | {response.provider}",
    ))
