import re
import aiosqlite
from pathlib import Path
from telethon import events
from core.registry import register_cmd
from helpers.hud import render
from helpers.shell import run
from core.errors import CommandError
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}backup(?:\s+(.*))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_backup,
        category="backup",
        description="Compresses local databases and pushes encrypted incremental backups to Rclone remote."
    )

async def handle_backup(event):
    await event.edit(render("CLOUD BACKUP", ["Checkpointing SQLite databases (TRUNCATE)..."]))

    db_dir = Path("data/databases")
    if db_dir.exists():
        for db_file in db_dir.glob("*.db"):
            try:
                async with aiosqlite.connect(db_file) as conn:
                    await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass

    await event.edit(render("CLOUD BACKUP", ["Syncing changed database files to remote..."]))

    remote_target = f"{config.RCLONE_REMOTE}astra_main/backups/"
    rc, out, err = await run(
        [
            "rclone", "sync", str(db_dir), remote_target,
            "--exclude", "*.db-wal",
            "--exclude", "*.db-shm",
            "--fast-list",
            "--transfers", "4"
        ],
        timeout=900,
    )

    if rc != 0:
        raise CommandError(f"Rclone sync failed (Code {rc}): {err[-300:]}")

    await event.edit(render(
        title="BACKUP COMPLETE",
        rows=[
            "Incremental sync finished successfully.",
            f"Target Remote: `{remote_target}`",
            "Excluded transient WAL/SHM locks."
        ],
        footer="backup | incremental sync"
    ))
