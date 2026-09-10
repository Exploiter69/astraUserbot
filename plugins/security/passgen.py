import re
import secrets
import string
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}passgen(?:\s+(.*))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_passgen,
        category="security",
        description="Generate a secure random password. Usage: .passgen [length]"
    )

async def handle_passgen(event):
    args = event.pattern_match.group(1)
    length = 16 # Default length
    
    if args:
        try:
            length = int(args.strip())
            if length < 8 or length > 128:
                raise CommandError("Password length must be between 8 and 128 characters.")
        except ValueError:
            raise CommandError("Invalid length provided. Must be an integer.")
            
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    
    await event.edit(render(
        title="PASSGEN",
        rows=[f"Length: {length}", "---", f"`{password}`"],
        footer="security | passgen"
    ))
