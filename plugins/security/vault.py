import re

from core.registry import register_cmd
from core.errors import CommandError
from core.services.secrets import SecretStore, SecretStoreError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}vault(?:\s+(.*))?$"
_MAX_KEY = 128
_MAX_VALUE = 4096

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_vault,
        category="security",
        description="Manage encrypted private key-value secrets. Usage: .vault [set|get|rm|list] [key] [val]",
    )


def _store() -> SecretStore:
    from core.context import get_application_context
    context = get_application_context()
    if context is not None:
        return context.get("secrets")
    return SecretStore()

async def handle_vault(event):
    args = event.pattern_match.group(1)
    if not args:
        raise CommandError("Usage: .vault set <key> <value> | get <key> | rm <key> | list")

    parts = args.split(maxsplit=2)
    action = parts[0].lower()
    store = _store()

    try:
        if action == "set":
            if len(parts) < 3:
                raise CommandError("Please provide a key and a value.")
            key, value = parts[1].strip(), parts[2]
            if not key or len(key) > _MAX_KEY:
                raise CommandError(f"Secret key must be 1-{_MAX_KEY} characters.")
            if len(value) > _MAX_VALUE:
                raise CommandError(f"Secret value must be {_MAX_VALUE} characters or fewer.")
            await store.set(key, value)
            await event.edit(render("VAULT", [f"Secret '{key}' stored encrypted."], footer="security | vault"))

        elif action == "get":
            if not event.is_private:
                raise CommandError("Secret values can only be revealed in Saved Messages/private chat.")
            if len(parts) < 2:
                raise CommandError("Please provide a key.")
            key = parts[1].strip()
            if not key or len(key) > _MAX_KEY:
                raise CommandError(f"Secret key must be 1-{_MAX_KEY} characters.")
            value = await store.get(key)
            if value is None:
                raise CommandError(f"No secret found for key '{key}'.")
            await event.edit(render("VAULT READ", [f"Key: {key}", "---", f"`{value}`"], footer="security | vault"))

        elif action == "rm":
            if len(parts) < 2:
                raise CommandError("Please provide a key.")
            key = parts[1].strip()
            if not key or len(key) > _MAX_KEY:
                raise CommandError(f"Secret key must be 1-{_MAX_KEY} characters.")
            await store.delete(key)
            await event.edit(render("VAULT", [f"Secret '{key}' deleted."], footer="security | vault"))

        elif action == "list":
            keys = await store.keys()
            rows = [f"- {key}" for key in keys[:100]] if keys else ["Vault is empty."]
            if len(keys) > 100:
                rows.append(f"... and {len(keys) - 100} more")
            await event.edit(render("VAULT KEYS", rows, footer="security | vault"))

        else:
            raise CommandError("Unknown action. Use set, get, rm, or list.")
    except SecretStoreError as exc:
        raise CommandError(str(exc)) from exc
