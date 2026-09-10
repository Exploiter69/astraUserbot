import re
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(qnote|qget|qlist)(?:\s+(.*))?$"
db = Database.get("quicknotes")

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS notes (
            tag TEXT PRIMARY KEY,
            content TEXT NOT NULL
        );
    """)
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_quicknote,
        category="advanced",
        description="Fast unencrypted quick notes. Usage: .qnote <tag> <text> | .qget <tag> | .qlist"
    )

async def handle_quicknote(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2) or ""

    if cmd == "qnote":
        parts = arg.split(maxsplit=1)
        tag = parts[0] if parts else ""
        content = parts[1] if len(parts) > 1 else ""

        if not content and event.is_reply:
            reply_msg = await event.get_reply_message()
            content = reply_msg.text or ""

        if not tag or not content:
            raise CommandError("Usage: .qnote <tag> <text> (or reply to a message)")

        await db.execute("INSERT OR REPLACE INTO notes (tag, content) VALUES (?, ?)", (tag, content))
        await event.edit(render(
            title="QUICK NOTE",
            rows=[f"Note saved successfully with tag: `{tag}`"],
            footer="advanced | qnote"
        ))

    elif cmd == "qget":
        tag = arg.strip()
        if not tag:
            raise CommandError("Please provide a note tag. Usage: .qget <tag>")

        row = await db.fetchone("SELECT content FROM notes WHERE tag = ?", (tag,))
        if not row:
            raise CommandError(f"No quick note found with tag '{tag}'.")

        await event.edit(render(
            title=f"NOTE // {tag}",
            rows=["---", row[0]],
            footer="advanced | qget"
        ))

    elif cmd == "qlist":
        rows = await db.fetchall("SELECT tag FROM notes")
        if not rows:
            await event.edit(render(
                title="QUICK NOTES",
                rows=["No quick notes stored."],
                footer="advanced | qlist"
            ))
            return

        tags = [f"• `{r[0]}`" for r in rows]
        await event.edit(render(
            title="STORED NOTES",
            rows=tags,
            footer="advanced | qlist"
        ))
