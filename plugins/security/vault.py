import re
import base64
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}vault(?:\s+(.*))?$"
db = Database.get("vault")

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS secrets (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_vault,
        category="security",
        description="Manage private key-value secrets. Usage: .vault [set|get|rm|list] [key] [val]"
    )

async def handle_vault(event):
    args = event.pattern_match.group(1)
    if not args:
        raise CommandError("Usage: .vault set <key> <value> | get <key> | rm <key> | list")
        
    parts = args.split(maxsplit=2)
    action = parts[0].lower()
    
    if action == "set":
        if len(parts) < 3:
            raise CommandError("Please provide a key and a value.")
        key, value = parts[1], parts[2]
        # Obfuscate value before storing (basic base64 to prevent raw plaintext queries on disk)
        encoded_val = base64.b64encode(value.encode('utf-8')).decode('utf-8')
        await db.execute("INSERT OR REPLACE INTO secrets (key, value) VALUES (?, ?)", (key, encoded_val))
        await event.edit(render(title="VAULT", rows=[f"Secret '{key}' stored securely."], footer="security | vault"))
        
    elif action == "get":
        if len(parts) < 2:
            raise CommandError("Please provide a key.")
        key = parts[1]
        row = await db.fetchone("SELECT value FROM secrets WHERE key = ?", (key,))
        if not row:
            raise CommandError(f"No secret found for key '{key}'.")
            
        decoded_val = base64.b64decode(row[0].encode('utf-8')).decode('utf-8')
        await event.edit(render(title="VAULT READ", rows=[f"Key: {key}", "---", f"`{decoded_val}`"], footer="security | vault"))
        
    elif action == "rm":
        if len(parts) < 2:
            raise CommandError("Please provide a key.")
        key = parts[1]
        await db.execute("DELETE FROM secrets WHERE key = ?", (key,))
        await event.edit(render(title="VAULT", rows=[f"Secret '{key}' deleted."], footer="security | vault"))
        
    elif action == "list":
        rows = await db.fetchall("SELECT key FROM secrets")
        if not rows:
            await event.edit(render(title="VAULT", rows=["Vault is empty."], footer="security | vault"))
            return
            
        keys = [f"- {row[0]}" for row in rows]
        await event.edit(render(title="VAULT KEYS", rows=keys, footer="security | vault"))
        
    else:
        raise CommandError("Unknown action. Use set, get, rm, or list.")
