"""Rebuildable SQLite projections derived from the durable Telegram event journal."""

from __future__ import annotations

import json
import time
from typing import Any

from core.services.storage import StorageService
from core.services.telegram_event_journal import TelegramEventJournal


class TelegramEventProjections:
    """Materialize bounded, rebuildable views from durable normalized events."""

    MAX_BATCH = 500
    MAX_TIMELINE = 100_000

    def __init__(self, storage: StorageService, journal: TelegramEventJournal) -> None:
        self.storage = storage
        self.journal = journal
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_latest_messages (
                message_id INTEGER NOT NULL,
                source_peer TEXT,
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                entity_id INTEGER,
                payload_json TEXT NOT NULL,
                observed_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        await self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_entity_observations (
                event_id TEXT PRIMARY KEY,
                entity_id INTEGER,
                source_peer TEXT,
                event_type TEXT NOT NULL,
                observed_at REAL NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        await self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                source_peer TEXT,
                entity_id INTEGER,
                message_id INTEGER,
                observed_at REAL NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        await self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_timeline_peer_time ON telegram_timeline(source_peer, observed_at DESC)"
        )
        await self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_timeline_entity_time ON telegram_timeline(entity_id, observed_at DESC)"
        )
        self._started = True

    async def close(self) -> None:
        self._started = False

    async def process_pending(self, *, limit: int = MAX_BATCH) -> int:
        """Project a bounded batch; failed events remain retryable in the journal."""
        if not self._started:
            raise RuntimeError("TelegramEventProjections is not started")
        rows = await self.journal.list_pending(limit=min(max(1, int(limit)), self.MAX_BATCH))
        processed = 0
        for row in rows:
            event_id = str(row["event_id"])
            if not await self.journal.mark_processing(event_id):
                continue
            try:
                payload = json.loads(row["payload_json"])
                statements = [
                    (
                        "INSERT OR IGNORE INTO telegram_timeline(event_id,event_type,source_peer,entity_id,message_id,observed_at,payload_json) VALUES (?,?,?,?,?,?,?)",
                        (
                            event_id,
                            row["event_type"],
                            row["source_peer"],
                            row["entity_id"],
                            row["message_id"],
                            row["observed_at"],
                            row["payload_json"],
                        ),
                    )
                ]
                if row["entity_id"] is not None:
                    statements.append(
                        (
                            "INSERT OR IGNORE INTO telegram_entity_observations(event_id,entity_id,source_peer,event_type,observed_at,payload_json) VALUES (?,?,?,?,?,?)",
                            (
                                event_id,
                                row["entity_id"],
                                row["source_peer"],
                                row["event_type"],
                                row["observed_at"],
                                row["payload_json"],
                            ),
                        )
                    )
                if row["event_type"] in {"MESSAGE_NEW", "MESSAGE_EDIT"} and row["message_id"] is not None:
                    statements.append(
                        (
                            "INSERT INTO telegram_latest_messages(message_id,source_peer,event_id,event_type,entity_id,payload_json,observed_at,updated_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET payload_json=excluded.payload_json, observed_at=excluded.observed_at, updated_at=excluded.updated_at",
                            (
                                row["message_id"],
                                row["source_peer"],
                                event_id,
                                row["event_type"],
                                row["entity_id"],
                                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                                row["observed_at"],
                                time.time(),
                            ),
                        )
                    )
                await self.storage.transaction(statements)
                await self.journal.mark_processed(event_id)
                processed += 1
            except Exception as exc:
                await self.journal.mark_failed(event_id, str(exc))
        await self._prune_timeline()
        return processed

    async def rebuild(self) -> int:
        """Clear derived projections and rebuild them from the durable journal."""
        if not self._started:
            raise RuntimeError("TelegramEventProjections is not started")
        await self.storage.transaction([
            ("DELETE FROM telegram_latest_messages", ()),
            ("DELETE FROM telegram_entity_observations", ()),
            ("DELETE FROM telegram_timeline", ()),
        ])
        rows = await self.storage.fetchall(
            "SELECT * FROM telegram_event_journal ORDER BY id LIMIT ?", (TelegramEventJournal.MAX_EVENTS,)
        )
        count = 0
        for row in rows:
            event_id = str(row["event_id"])
            payload = json.loads(row["payload_json"])
            statements = [
                (
                    "INSERT OR IGNORE INTO telegram_timeline(event_id,event_type,source_peer,entity_id,message_id,observed_at,payload_json) VALUES (?,?,?,?,?,?,?)",
                    (event_id, row["event_type"], row["source_peer"], row["entity_id"], row["message_id"], row["observed_at"], row["payload_json"]),
                )
            ]
            if row["entity_id"] is not None:
                statements.append((
                    "INSERT OR IGNORE INTO telegram_entity_observations(event_id,entity_id,source_peer,event_type,observed_at,payload_json) VALUES (?,?,?,?,?,?)",
                    (event_id, row["entity_id"], row["source_peer"], row["event_type"], row["observed_at"], row["payload_json"]),
                ))
            if row["event_type"] in {"MESSAGE_NEW", "MESSAGE_EDIT"} and row["message_id"] is not None:
                statements.append((
                    "INSERT OR IGNORE INTO telegram_latest_messages(message_id,source_peer,event_id,event_type,entity_id,payload_json,observed_at,updated_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET payload_json=excluded.payload_json, observed_at=excluded.observed_at, updated_at=excluded.updated_at",
                    (row["message_id"], row["source_peer"], event_id, row["event_type"], row["entity_id"], json.dumps(payload, sort_keys=True, separators=(",", ":")), row["observed_at"], time.time()),
                ))
            await self.storage.transaction(statements)
            count += 1
        return count

    async def _prune_timeline(self) -> None:
        row = await self.storage.fetchone("SELECT COUNT(*) AS count FROM telegram_timeline")
        count = int(row["count"]) if row else 0
        if count > self.MAX_TIMELINE:
            await self.storage.execute(
                "DELETE FROM telegram_timeline WHERE id IN (SELECT id FROM telegram_timeline ORDER BY id LIMIT ?)",
                (min(count - self.MAX_TIMELINE, 1000),),
            )
