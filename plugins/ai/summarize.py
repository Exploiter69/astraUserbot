import re
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from plugins.ai.groq_client import get_chat_completion
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}summarize$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_summarize,
        category="ai",
        description="Summarize a replied text message."
    )

async def handle_summarize(event):
    if not event.is_reply:
        raise CommandError("Please reply to a text message to summarize it.")
        
    reply_msg = await event.get_reply_message()
    text_to_summarize = reply_msg.text
    
    if not text_to_summarize:
        raise CommandError("The replied message does not contain any text.")

    await event.edit(render(
        title="AI SUMMARIZATION",
        rows=["Analyzing text..."],
        footer="ai | summarize"
    ))
    
    messages = [
        {"role": "system", "content": "You are a concise assistant. Provide a brief, bulleted summary of the following text, extracting only the most critical information."},
        {"role": "user", "content": text_to_summarize}
    ]
    
    response_text = await get_chat_completion(messages, model="llama3-8b-8192")
    
    rows = ["---"] + response_text.split('\n')
    await event.edit(render(
        title="SUMMARY",
        rows=rows,
        footer="ai | summarize"
    ))
