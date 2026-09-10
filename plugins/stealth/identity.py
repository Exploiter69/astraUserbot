import re
import os
import html
from pathlib import Path
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest, GetUserPhotosRequest
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from helpers.entity import resolve_target
from config import config

db = Database.get("identity")
PATTERN = rf"^{re.escape(config.PREFIX)}(clone|revert)(?:\s+(.*))?$"

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS my_profile (
            id INTEGER PRIMARY KEY CHECK (id=1), 
            first_name TEXT, last_name TEXT, bio TEXT
        );
    """)
    register_cmd(client, PATTERN, handle_identity, "stealth", "Identity mirroring stealth tools (.clone / .revert).")

async def get_user_from_event(event):
    try:
        if event.is_reply:
            reply_message = await event.get_reply_message()
            if reply_message and reply_message.sender_id:
                return await event.client.get_entity(reply_message.sender_id)
        
        args = event.pattern_match.group(2)
        if args:
            user_input = args.strip()
            return await event.client.get_entity(user_input)
            
        return None
    except Exception:
        return None

async def handle_identity(event):
    cmd = event.pattern_match.group(1).lower()
    client = event.client
    
    if cmd == "clone":
        target = await get_user_from_event(event)
        if not target:
            try:
                target = await resolve_target(event)
            except Exception:
                pass
                
        if not target:
            raise CommandError("Reply to a user or provide a username/ID to clone!")
            
        me = await client.get_me()
        
        try:
            target_full = await client(GetFullUserRequest(target))
            target_bio = target_full.about or ""
        except Exception:
            target_bio = ""
            
        try:
            my_full = await client(GetFullUserRequest("me"))
            my_bio = my_full.about or ""
        except Exception:
            my_bio = ""

        await db.execute(
            "INSERT OR REPLACE INTO my_profile (id, first_name, last_name, bio) VALUES (1, ?, ?, ?)", 
            (me.first_name, me.last_name, my_bio)
        )
                         
        first_name = html.escape(getattr(target, 'first_name', '') or "")
        last_name = html.escape(getattr(target, 'last_name', '') or "")
        
        await client(UpdateProfileRequest(
            first_name=first_name, 
            last_name=last_name, 
            about=target_bio
        ))
        
        dp_status = "Name & Bio cloned."
        try:
            cache_dir = Path("data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            photo_path = cache_dir / "target_dp.jpg"
            
            downloaded = await client.download_profile_photo(target, file=str(photo_path))
            if downloaded and os.path.exists(downloaded):
                with open(downloaded, 'rb') as f:
                    file_handle = await client.upload_file(f)
                    await client(UploadProfilePhotoRequest(file=file_handle))
                os.remove(downloaded)
                dp_status = "Full identity (Name, Bio, & DP) cloned."
        except Exception:
            pass

        await event.edit(render("IDENTITY CLONE", [f"Mirrored target ID: {target.id}", dp_status]))
        
    elif cmd == "revert":
        row = await db.fetchone("SELECT first_name, last_name, bio FROM my_profile WHERE id=1")
        if row:
            await client(UpdateProfileRequest(first_name=row[0], last_name=row[1], about=row[2] or ""))
            
            try:
                photos = await client(GetUserPhotosRequest(user_id="me", offset=0, max_id=0, limit=1))
                if photos.photos:
                    await client(DeletePhotosRequest(id=[photos.photos[0]]))
            except Exception:
                pass
                
            await event.edit(render("IDENTITY REVERT", ["Restored original profile identity, bio, and photo."]))
        else:
            raise CommandError("No profile snapshot found in database. Clone a profile first!")
