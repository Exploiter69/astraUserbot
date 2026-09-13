import re
import uuid
from pathlib import Path

from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import DeletePhotosRequest, GetUserPhotosRequest, UploadProfilePhotoRequest

from core.database import Database
from core.errors import CommandError
from core.registry import register_cmd
from helpers.entity import resolve_target
from helpers.hud import render
from config import config

db = Database.get("identity")

PATTERN = rf"^{re.escape(config.PREFIX)}(clone|revert|backup)(?:\s+(.*))?$"
_PROFILE_DIR = Path("data/cache/identity")
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
    try:
        await db.execute("ALTER TABLE my_profile ADD COLUMN photo_path TEXT")
    except Exception:
        pass

    register_cmd(client, PATTERN, handle_identity, "stealth", "Identity mirroring tools (.clone / .revert / .backup).")


async def _snapshot_profile(client):
    me = await client.get_me()
    try:
        full = await client(GetFullUserRequest("me"))
        bio = full.about or ""
    except Exception:
        bio = ""

    old_row = await db.fetchone("SELECT photo_path FROM my_profile WHERE id=1")
    old_path = str(old_row[0]) if old_row and old_row[0] else None
    photo_path: str | None = None
    if getattr(me, "photo", None):
        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        candidate = _PROFILE_DIR / f"original_{uuid.uuid4().hex}.jpg"
        try:
            downloaded = await client.download_profile_photo("me", file=str(candidate))
        except Exception as exc:
            candidate.unlink(missing_ok=True)
            raise CommandError("Could not snapshot the current profile photo; no profile changes were made.") from exc
        if not downloaded or not candidate.is_file() or candidate.stat().st_size <= 0:
            candidate.unlink(missing_ok=True)
            raise CommandError("Could not snapshot the current profile photo; no profile changes were made.")
        photo_path = str(candidate)

    await db.execute(
        "INSERT OR REPLACE INTO my_profile (id, first_name, last_name, bio, photo_path) VALUES (1, ?, ?, ?, ?)",
        ((me.first_name or "")[:_MAX_NAME], (me.last_name or "")[:_MAX_NAME], bio[:_MAX_BIO], photo_path),
    )
    if old_path and old_path != photo_path:
        try:
            Path(old_path).unlink(missing_ok=True)
        except OSError:
            pass


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


async def _restore_photo(client, photo_path: str | None):
    if photo_path:
        path = Path(photo_path).resolve()
        try:
            path.relative_to(_PROFILE_DIR.resolve())
        except ValueError as exc:
            raise CommandError("Saved profile photo is outside the managed identity cache.") from exc
        if not path.is_file() or path.stat().st_size <= 0:
            raise CommandError("Saved profile photo is missing or invalid.")
        # Upload first so a failed upload cannot destroy the current profile photo.
        with open(path, "rb") as handle:
            uploaded = await client.upload_file(handle)
        await client(UploadProfilePhotoRequest(file=uploaded))
        return

    photos = await client(GetUserPhotosRequest(user_id="me", offset=0, max_id=0, limit=100))
    if photos.photos:
        await client(DeletePhotosRequest(id=list(photos.photos)))


async def handle_identity(event):
    cmd = event.pattern_match.group(1).lower()
    client = event.client

    if cmd == "backup":
        await _snapshot_profile(client)
        await event.edit(render("IDENTITY BACKUP", ["Original profile snapshot saved."], footer="stealth | backup"))
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
        if target.id == config.OWNER_ID:
            raise CommandError("Cannot clone the owner account onto itself.")

        await _snapshot_profile(client)
        try:
            target_full = await client(GetFullUserRequest(target))
            target_bio = (target_full.about or "")[:_MAX_BIO]
        except Exception as exc:
            raise CommandError("Could not read the target profile; no identity changes were made.") from exc

        await client(UpdateProfileRequest(
            first_name=(getattr(target, "first_name", "") or "")[:_MAX_NAME],
            last_name=(getattr(target, "last_name", "") or "")[:_MAX_NAME],
            about=target_bio,
        ))

        dp_status = "Name & Bio cloned. Target profile photo was not available."
        target_photo = _PROFILE_DIR / f"target_{uuid.uuid4().hex}.jpg"
        try:
            _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            downloaded = await client.download_profile_photo(target, file=str(target_photo))
            if downloaded and target_photo.is_file() and target_photo.stat().st_size > 0:
                with open(target_photo, "rb") as handle:
                    uploaded = await client.upload_file(handle)
                await client(UploadProfilePhotoRequest(file=uploaded))
                dp_status = "Full identity (Name, Bio, & DP) cloned."
        except Exception:
            dp_status = "Name & Bio cloned. Target profile photo could not be cloned."
        finally:
            target_photo.unlink(missing_ok=True)

        await event.edit(render("IDENTITY CLONE", [f"Mirrored target ID: {target.id}", dp_status]))
        return

    if cmd == "revert":
        row = await db.fetchone("SELECT first_name, last_name, bio, photo_path FROM my_profile WHERE id=1")
        if not row:
            raise CommandError("No profile snapshot found. Use .clone or .backup first.")
        await client(UpdateProfileRequest(first_name=row[0] or "", last_name=row[1] or "", about=row[2] or ""))
        try:
            await _restore_photo(client, row[3])
        except Exception as exc:
            raise CommandError("Profile text was restored, but photo restoration failed; the current photo was left unchanged.") from exc
        await event.edit(render("IDENTITY REVERT", ["Restored the saved profile identity and original photo."], footer="stealth | revert"))
        return

    raise CommandError("Unsupported identity operation.")
