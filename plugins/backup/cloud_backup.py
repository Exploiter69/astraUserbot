import re
import aiosqlite
from pathlib import Path

from core.context import get_application_context
from core.registry import register_cmd
from helpers.hud import render
from core.errors import CommandError
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}backup(?:\s+(.*))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_backup,
        category="backup",
        description="Checkpoint local SQLite databases and sync them to the configured Rclone remote."
    )

async def handle_backup(event):
    context = get_application_context()
    if context is None:
        raise CommandError("Subprocess service is unavailable.")
    subprocess = context.get("subprocess")

    await event.edit(render("CLOUD BACKUP", ["Checkpointing SQLite databases (TRUNCATE)..."]))

    db_dir = Path("data/databases")
    if db_dir.exists():
        for db_file in db_dir.glob("*.db"):
            try:
                async with aiosqlite.connect(db_file) as conn:
                    await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as exc:
                raise CommandError(f"Database checkpoint failed for {db_file.name}.") from exc

    await event.edit(render("CLOUD BACKUP", ["Syncing changed database files to remote..."]))

    remote_target = f"{config.RCLONE_REMOTE}astra_main/backups/"
    try:
        result = await subprocess.run(
            [
                "rclone", "sync", str(db_dir), remote_target,
                "--exclude", "*.db-wal",
                "--exclude", "*.db-shm",
                "--fast-list",
                "--transfers", "4"
            ],
            timeout=900,
            max_output_bytes=256 * 1024,
        )
    except Exception as exc:
        raise CommandError("Rclone backup execution failed.") from exc

    if result.returncode != 0:
        raise CommandError(f"Rclone sync failed (Code {result.returncode}): {result.stderr[-300:]}")

    await event.edit(render(
        title="BACKUP COMPLETE",
        rows=[
            "Incremental sync finished successfully.",
            f"Target Remote: `{remote_target}`",
            "Excluded transient WAL/SHM locks."
        ],
        footer="backup | incremental sync"
    ))
