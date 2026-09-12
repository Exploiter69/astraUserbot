import os
import re
from pathlib import Path

from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import (
    DeletePhotosRequest,
    GetUserPhotosRequest,
    UploadProfilePhotoRequest,
)

from core.database import Database
from core.errors import CommandError
from core.registry import register_cmd
from helpers.entity import resolve_target
from helpers.hud import render
from config import config

db = Database.get("identity")

PATTERN = rf"^{re.escape(config.PREFIX)}(clone|revert)(?:\s+(.*))?$"

_PROFILE_PHOTO = Path("data/cache/identity_original_dp.jpg")
_MAX_NAME = 70
_MAX_BIO = 70


async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS my_profile (
            id INTEGER PRIMARY KEY CHECK (id=1),
            first_name TEXT,
            last_name TEXT,
            bio TEXT,
            photo_path TEXT
        );
    """)
    # Existing installations may have the old three-column schema.
    try:
        await db.execute("ALTER TABLE my_profile ADD COLUMN photo_path TEXT")
    except Exception:
        pass

    register_cmd(
        client,
        PATTERN,
        handle_identity,
        "stealth",
        "Identity mirroring tools (.clone / .revert / .backup).",
    )


async def _snapshot_profile(client):
    me = await client.get_me()
    try:
        full = await client(GetFullUserRequest("me"))
        bio = full.about or ""
    except Exception:
        bio = ""

    photo_path = None
    try:
        _PROFILE_PHOTO.parent.mkdir(parents=True, exist_ok=True)
        downloaded = await client.download_profile_photo(
            "me",
            file=str(_PROFILE_PHOTO),
        )
        if downloaded and os.path.exists(downloaded):
            photo_path = str(_PROFILE_PHOTO)
    except Exception:
        photo_path = None

    await db.execute(
        """
        INSERT OR REPLACE INTO my_profile
        (id, first_name, last_name, bio, photo_path)
        VALUES (1, ?, ?, ?, ?)
        """,
        (
            (me.first_name or "")[:_MAX_NAME],
            (me.last_name or "")[:_MAX_NAME],
            bio[:_MAX_BIO],
            photo_path,
        ),
    )


async def get_user_from_event(event):
    try:
        if event.is_reply:
            reply_message = await event.get_reply_message()
            if reply_message and reply_message.sender_id:
                return await event.client.get_entity(reply_message.sender_id)

        args = event.pattern_match.group(2)
        if args:
            return await event.client.get_entity(args.strip())
    except Exception:
        return None
    return None


async def _restore_photo(client, photo_path):
    photos = await client(
        GetUserPhotosRequest(user_id="me", offset=0, max_id=0, limit=100)
    )
    if photos.photos:
        await client(DeletePhotosRequest(id=list(photos.photos)))

    if photo_path and os.path.exists(photo_path):
        with open(photo_path, "rb") as handle:
            uploaded = await client.upload_file(handle)
        await client(UploadProfilePhotoRequest(file=uploaded))


async def handle_identity(event):
    cmd = event.pattern_match.group(1).lower()
    client = event.client

    if cmd == "backup":
        await _snapshot_profile(client)
        await event.edit(
            render(
                "IDENTITY BACKUP",
                ["Original profile snapshot saved."],
                footer="stealth | backup",
            )
        )
        return

    if cmd == "clone":
        target = await get_user_from_event(event)
        if not target:
            try:
                target = await resolve_target(event)
            except Exception:
                target = None

        if not target:
            raise CommandError("Reply to a user or provide a username/ID to clone.")

        await _snapshot_profile(client)

        try:
            target_full = await client(GetFullUserRequest(target))
            target_bio = (target_full.about or "")[:_MAX_BIO]
        except Exception:
            target_bio = ""

        first_name = (getattr(target, "first_name", "") or "")[:_MAX_NAME]
        last_name = (getattr(target, "last_name", "") or "")[:_MAX_NAME]

        await client(
            UpdateProfileRequest(
                first_name=first_name,
                last_name=last_name,
                about=target_bio,
            )
        )

        dp_status = "Name & Bio cloned."
        try:
            cache_dir = Path("data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            photo_path = cache_dir / "target_dp.jpg"
            downloaded = await client.download_profile_photo(
                target,
                file=str(photo_path),
            )
            if downloaded and os.path.exists(downloaded):
                with open(downloaded, "rb") as handle:
                    uploaded = await client.upload_file(handle)
                await client(UploadProfilePhotoRequest(file=uploaded))
                os.remove(downloaded)
                dp_status = "Full identity (Name, Bio, & DP) cloned."
        except Exception:
            pass

        await event.edit(
            render(
                "IDENTITY CLONE",
                [f"Mirrored target ID: {target.id}", dp_status],
            )
        )
        return

    if cmd == "revert":
        row = await db.fetchone(
            "SELECT first_name, last_name, bio, photo_path FROM my_profile WHERE id=1"
        )
        if not row:
            raise CommandError(
                "No profile snapshot found. Use .clone or .backup first."
            )

        await client(
            UpdateProfileRequest(
                first_name=row[0] or "",
                last_name=row[1] or "",
                about=row[2] or "",
            )
        )
        try:
            await _restore_photo(client, row[3])
        except Exception as exc:
            raise CommandError("Profile identity restored, but photo restoration failed.") from exc

        await event.edit(
            render(
                "IDENTITY REVERT",
                ["Restored the saved profile identity and original photo."],
                footer="stealth | revert",
            )
        )
        return

    raise CommandError("Unsupported identity operation.")
