import re
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(qnote|qget|qlist|qdel)(?:\s+(.*))?$"

_MAX_TAG = 64
_MAX_CONTENT = 3500
_MAX_LIST = 50
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
        description="Fast unencrypted quick notes. Usage: .qnote <tag> <text> | .qget <tag> | .qlist | .qdel <tag>"
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
        if len(tag) > _MAX_TAG:
            raise CommandError(f"Note tag is too long (max {_MAX_TAG} characters).")
        if len(content) > _MAX_CONTENT:
            raise CommandError(f"Note content is too long (max {_MAX_CONTENT} characters).")

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

        content = row[0]
        if len(content) > _MAX_CONTENT:
            content = content[:_MAX_CONTENT] + "\n[truncated]"
        await event.edit(render(
            title=f"NOTE // {tag}",
            rows=["---", content],
            footer="advanced | qget"
        ))

    elif cmd in {"qdel", "del"}:
        tag = arg.strip()
        if not tag:
            raise CommandError("Please provide a note tag. Usage: .qdel <tag>")
        cursor = await db.execute("DELETE FROM notes WHERE tag = ?", (tag,))
        if cursor.rowcount == 0:
            raise CommandError(f"No quick note found with tag '{tag}'.")
        await event.edit(render(
            title="QUICK NOTE",
            rows=[f"Deleted note: `{tag}`"],
            footer="advanced | qdel"
        ))

    elif cmd == "qlist":
        rows = await db.fetchall("SELECT tag FROM notes ORDER BY tag LIMIT ?", (_MAX_LIST,))
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
