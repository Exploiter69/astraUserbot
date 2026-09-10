import re
import time
from telethon import events
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from helpers.entity import resolve_target
from config import config

db = Database.get("account_archiver")
PATTERN_ARCH = rf"^{re.escape(config.PREFIX)}arch(?:\s+(status|stats|search))?(?:\s+(.*))?$"
PATTERN_TRACK = rf"^{re.escape(config.PREFIX)}track(?:\s+(add|remove|list))?(?:\s+(.*))?$"

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS arch_settings (
            key TEXT PRIMARY KEY, 
            val INTEGER
        );
        INSERT OR IGNORE INTO arch_settings (key, val) VALUES ('enabled', 1);

        CREATE TABLE IF NOT EXISTS group_watchlist (
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS user_accounts (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            is_bot INTEGER,
            is_verified INTEGER,
            first_seen REAL,
            last_seen REAL
        );

        CREATE TABLE IF NOT EXISTS account_messages (
            message_id INTEGER,
            chat_id INTEGER,
            user_id INTEGER,
            text TEXT,
            media_type TEXT,
            timestamp REAL,
            PRIMARY KEY (message_id, chat_id)
        );
    """)
    register_cmd(client, PATTERN_ARCH, handle_arch, "security", "Universal account DM and watchlist archiver.")
    register_cmd(client, PATTERN_TRACK, handle_track, "security", "Manage group archiving watchlist.")
    client.add_event_handler(archive_watcher, events.NewMessage(incoming=True))

async def handle_arch(event):
    cmd = (event.pattern_match.group(1) or "").lower()
    arg = (event.pattern_match.group(2) or "").strip()

    if cmd == "status":
        if arg:
            # Explicitly setting state if "on" or "off" is passed
            state = 1 if arg.lower() in ("on", "1", "true", "enable") else 0
            await db.execute("UPDATE arch_settings SET val = ? WHERE key = 'enabled'", (state,))
        
        # Always fetch current state from DB to display accurately
        row = await db.fetchone("SELECT val FROM arch_settings WHERE key = 'enabled'")
        current_state = row[0] if row else 0
        
        await event.edit(render("ARCHIVER STATUS", [f"Global Archiving: {'ENABLED' if current_state else 'DISABLED'}"]))
        
    elif cmd == "stats":
        users_count = await db.fetchone("SELECT COUNT(*) FROM user_accounts")
        msg_count = await db.fetchone("SELECT COUNT(*) FROM account_messages")
        
        await event.edit(render(
            title="ARCHIVER STATS",
            rows=[
                f"Unique Accounts Tracked: {users_count[0]}",
                f"Total Messages Logged: {msg_count[0]}"
            ],
            footer="security | archiver"
        ))
        
    elif cmd == "search":
        if not arg:
            raise CommandError("Please provide a keyword to search.")
            
        rows = await db.fetchall("""
            SELECT u.username, u.first_name, m.text 
            FROM account_messages m
            JOIN user_accounts u ON m.user_id = u.user_id
            WHERE m.text LIKE ?
            ORDER BY m.timestamp DESC LIMIT 10
        """, (f"%{arg}%",))
        
        if not rows:
            raise CommandError(f"No results found for '{arg}'.")
            
        display_rows = ["Search Results:", "---"]
        for r in rows:
            name_display = r[0] if r[0] else r[1]
            content = r[2][:45] + "..." if len(r[2]) > 45 else r[2]
            display_rows.append(f"[{name_display}]: {content}")
            
        await event.edit(render("ARCHIVER SEARCH", display_rows, footer="security | archiver"))
    else:
        raise CommandError("Usage: .arch status [on/off] | .arch stats | .arch search <keyword>")

async def handle_track(event):
    cmd = (event.pattern_match.group(1) or "").lower()
    
    if cmd == "list":
        rows = await db.fetchall("SELECT user_id FROM group_watchlist WHERE chat_id = ?", (event.chat_id,))
        if not rows:
            await event.edit(render("WATCHLIST", ["No users are tracked in this group."]))
            return
            
        display = [f"- {r[0]}" for r in rows]
        await event.edit(render(f"WATCHLIST: {event.chat_id}", display))
        return
        
    target = await resolve_target(event)
    
    if cmd == "add":
        await db.execute("INSERT OR IGNORE INTO group_watchlist (chat_id, user_id) VALUES (?, ?)", (event.chat_id, target.id))
        await event.edit(render("WATCHLIST UPDATED", [f"Now tracking {target.id} in this group."]))
    elif cmd == "remove":
        await db.execute("DELETE FROM group_watchlist WHERE chat_id = ? AND user_id = ?", (event.chat_id, target.id))
        await event.edit(render("WATCHLIST UPDATED", [f"Stopped tracking {target.id} in this group."]))
    else:
        raise CommandError("Usage: .track add | remove | list")

async def archive_watcher(event):
    if not event.sender_id:
        return
        
    status = await db.fetchone("SELECT val FROM arch_settings WHERE key = 'enabled'")
    if not status or status[0] == 0:
        return

    should_log = False
    
    if event.is_private:
        should_log = True
    elif event.is_group or event.is_channel:
        row = await db.fetchone("SELECT 1 FROM group_watchlist WHERE chat_id = ? AND user_id = ?", (event.chat_id, event.sender_id))
        if row:
            should_log = True

    if not should_log:
        return

    try:
        sender = await event.get_sender()
        now = time.time()
        
        username = getattr(sender, 'username', None)
        first_name = getattr(sender, 'first_name', None)
        last_name = getattr(sender, 'last_name', None)
        is_bot = 1 if getattr(sender, 'bot', False) else 0
        is_verified = 1 if getattr(sender, 'verified', False) else 0

        # Upsert user metadata ledger
        await db.execute("""
            INSERT INTO user_accounts (user_id, username, first_name, last_name, is_bot, is_verified, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen=excluded.last_seen
        """, (event.sender_id, username, first_name, last_name, is_bot, is_verified, now, now))

        media_type = type(event.media).__name__ if event.media else None

        # Archive message payload
        await db.execute("""
            INSERT OR IGNORE INTO account_messages (message_id, chat_id, user_id, text, media_type, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event.id, event.chat_id, event.sender_id, event.text or "", media_type, now))
    except Exception:
        pass
