import re

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render

PATTERN = rf"^{re.escape(config.PREFIX)}ask(?:\s+(.*))?$"


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_ask,
        category="ai",
        description="Ask the configured AI provider a question. Usage: .ask <prompt>",
    )


async def handle_ask(event):
    prompt = event.pattern_match.group(1)
    if not prompt and event.is_reply:
        reply_msg = await event.get_reply_message()
        prompt = reply_msg.text
    if not prompt:
        raise CommandError("Please provide a prompt or reply to a text message.")

    context = get_application_context()
    if context is None:
        raise CommandError("AI service is unavailable.")
    service = context.get("ai")

    await event.edit(render(
        title="LLM INFERENCE",
        rows=[f"Routing query to {service.provider_name}..."],
        footer="ai | ask",
    ))
    response = await service.chat([{"role": "user", "content": prompt}])
    await event.edit(render(
        title="AI RESPONSE",
        rows=response.text.split("\n"),
        footer=f"ai | ask | {response.provider}",
    ))
