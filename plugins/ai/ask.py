import re
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from plugins.ai.groq_client import get_chat_completion
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}ask(?:\s+(.*))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_ask,
        category="ai",
        description="Ask the Groq LLaMA3 model a question. Usage: .ask <prompt>"
    )

async def handle_ask(event):
    prompt = event.pattern_match.group(1)
    
    if not prompt and event.is_reply:
        reply_msg = await event.get_reply_message()
        prompt = reply_msg.text
        
    if not prompt:
        raise CommandError("Please provide a prompt or reply to a text message.")
        
    await event.edit(render(
        title="LLM INFERENCE",
        rows=["Routing query to Groq Cloud..."],
        footer="ai | ask"
    ))
    
    messages = [{"role": "user", "content": prompt}]
    
    # Execution is yielded back to the loop while awaiting HTTP response
    response_text = await get_chat_completion(messages)
    
    rows = response_text.split('\n')
    await event.edit(render(
        title="AI RESPONSE",
        rows=rows,
        footer="ai | ask"
    ))
