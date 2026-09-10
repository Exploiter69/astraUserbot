import re
import hashlib
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.concurrency import run_in_thread
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}hash(?:\s+(.*))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_hash,
        category="security",
        description="Generate MD5, SHA1, and SHA256 hashes of a string."
    )

def _compute_hashes(text: str) -> dict[str, str]:
    """Synchronous heavy compute function to be run in a thread pool."""
    encoded = text.encode('utf-8')
    return {
        "MD5": hashlib.md5(encoded).hexdigest(),
        "SHA1": hashlib.sha1(encoded).hexdigest(),
        "SHA256": hashlib.sha256(encoded).hexdigest()
    }

async def handle_hash(event):
    text = event.pattern_match.group(1)
    
    if not text and event.is_reply:
        reply_msg = await event.get_reply_message()
        text = reply_msg.text
        
    if not text:
        raise CommandError("Please provide text or reply to a message to hash.")

    # Prevent potential event-loop blocks on very large text inputs
    hashes = await run_in_thread(_compute_hashes, text)
    
    rows = [
        f"MD5: `{hashes['MD5']}`",
        f"SHA1: `{hashes['SHA1']}`",
        f"SHA256: `{hashes['SHA256']}`"
    ]
    
    await event.edit(render(
        title="HASH GENERATOR",
        rows=rows,
        footer="security | hash"
    ))
