import asyncio
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}backup(?:\s+(.*))?$"

DB_DIR = Path("data/databases")


def _snapshot_sqlite(source: Path, destination: Path) -> None:
    source_conn = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(destination_conn)
        destination_conn.commit()
    finally:
        destination_conn.close()
        source_conn.close()


async def setup(client):
    if not shutil.which("rclone"):
        return
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_backup,
        category="backup",
        description="Create consistent local SQLite snapshots and copy them to the configured Rclone remote.",
    )


async def handle_backup(event):
    context = get_application_context()
    if context is None:
        raise CommandError("Subprocess service is unavailable.")
    subprocess = context.get("subprocess")

    if not DB_DIR.exists():
        raise CommandError("Database directory does not exist.")

    await event.edit(
        render(
            "CLOUD BACKUP",
            ["Creating consistent SQLite snapshots..."],
            footer="backup",
        )
    )

    with tempfile.TemporaryDirectory(prefix="astra-backup-") as tmp:
        snapshot_dir = Path(tmp)

        db_files = sorted(DB_DIR.glob("*.db"))
        if not db_files:
            raise CommandError("No SQLite databases found.")

        copied = []
        for db_file in db_files:
            destination = snapshot_dir / db_file.name
            try:
                await asyncio.to_thread(_snapshot_sqlite, db_file, destination)
                copied.append(destination)
            except Exception as exc:
                raise CommandError(
                    f"Could not snapshot database {db_file.name}."
                ) from exc

        remote_target = f"{config.RCLONE_REMOTE}astra_main/backups/"

        await event.edit(
            render(
                "CLOUD BACKUP",
                [f"Uploading {len(copied)} consistent database snapshots..."],
                footer="backup",
            )
        )

        try:
            result = await subprocess.run(
                [
                    "rclone",
                    "copy",
                    str(snapshot_dir),
                    remote_target,
                    "--fast-list",
                    "--transfers",
                    "4",
                ],
                timeout=900,
                max_output_bytes=256 * 1024,
            )
        except Exception as exc:
            raise CommandError("Rclone backup execution failed.") from exc

        if result.returncode != 0:
            raise CommandError(
                f"Rclone backup failed (code {result.returncode})."
            )

    await event.edit(
        render(
            "BACKUP COMPLETE",
            [
                f"Created and uploaded {len(copied)} consistent SQLite snapshots.",
                f"Target Remote: `{remote_target}`",
                "Existing remote files were not deleted.",
            ],
            footer="backup | safe copy",
        )
    )
