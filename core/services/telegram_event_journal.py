"""Durable, bounded SQLite journal for normalized Telegram events."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from typing import Any

from core.services.telegram_events import TelegramEvent
from core.services.storage import StorageService


class TelegramEventJournal:
    """Persist normalized Telegram events without retaining raw Telethon objects."""

    MAX_EVENTS = 100_000
    PRUNE_BATCH = 1_000

    def __init__(self, storage: StorageService) -> None:
        self.storage = storage
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.storage.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_event_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                fingerprint TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                observed_at REAL NOT NULL,
                source_peer TEXT,
                message_id INTEGER,
                entity_id INTEGER,
                payload_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                processing_state TEXT NOT NULL DEFAULT 'PENDING',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at REAL NOT NULL,
                processed_at REAL
            )
            """
        )
        await self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_event_type_time ON telegram_event_journal(event_type, observed_at DESC)"
        )
        await self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_event_peer_time ON telegram_event_journal(source_peer, observed_at DESC)"
        )
        await self.storage.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_event_state_time ON telegram_event_journal(processing_state, created_at)"
        )
        self._started = True

    async def close(self) -> None:
        self._started = False

    @staticmethod
    def fingerprint(event: TelegramEvent) -> str:
        canonical = {
            "event_type": event.event_type,
            "source_peer": event.source_peer,
            "message_id": event.message_id,
            "entity_id": event.entity_id,
            "payload": event.payload,
            "schema_version": event.schema_version,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def append(self, event: TelegramEvent) -> bool:
        """Append an event; return False when an equivalent event is already journaled."""
        if not self._started:
            raise RuntimeError("TelegramEventJournal is not started")
        fingerprint = self.fingerprint(event)
        payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), default=str)
        now = time.time()
        try:
            await self.storage.execute(
                """
                INSERT INTO telegram_event_journal
                (event_id, fingerprint, event_type, observed_at, source_peer, message_id,
                 entity_id, payload_json, schema_version, processing_state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    event.event_id,
                    fingerprint,
                    event.event_type,
                    event.observed_at,
                    event.source_peer,
                    event.message_id,
                    event.entity_id,
                    payload,
                    event.schema_version,
                    now,
                ),
            )
        except Exception as exc:
            # The unique fingerprint is the idempotency boundary. Avoid making a
            # duplicate event a failed Telegram operation for downstream callers.
            if "UNIQUE constraint failed: telegram_event_journal.fingerprint" in str(exc):
                return False
            raise
        await self._prune()
        return True

    async def get(self, event_id: str) -> dict[str, Any] | None:
        row = await self.storage.fetchone(
            "SELECT * FROM telegram_event_journal WHERE event_id=?", (event_id,)
        )
        return dict(row) if row else None

    async def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1000))
        rows = await self.storage.fetchall(
            "SELECT * FROM telegram_event_journal WHERE processing_state='PENDING' ORDER BY id LIMIT ?",
            (bounded,),
        )
        return [dict(row) for row in rows]

    async def mark_processing(self, event_id: str) -> bool:
        cursor = await self.storage.execute(
            """
            UPDATE telegram_event_journal
            SET processing_state='PROCESSING', attempt_count=attempt_count+1, last_error=NULL
            WHERE event_id=? AND processing_state IN ('PENDING', 'FAILED')
            """,
            (event_id,),
        )
        return cursor.rowcount == 1

    async def mark_processed(self, event_id: str) -> bool:
        cursor = await self.storage.execute(
            """
            UPDATE telegram_event_journal
            SET processing_state='PROCESSED', processed_at=?, last_error=NULL
            WHERE event_id=? AND processing_state='PROCESSING'
            """,
            (time.time(), event_id),
        )
        return cursor.rowcount == 1

    async def mark_failed(self, event_id: str, error: str) -> bool:
        bounded_error = str(error)[:1024]
        cursor = await self.storage.execute(
            """
            UPDATE telegram_event_journal
            SET processing_state='FAILED', last_error=?
            WHERE event_id=? AND processing_state='PROCESSING'
            """,
            (bounded_error, event_id),
        )
        return cursor.rowcount == 1

    async def _prune(self) -> None:
        row = await self.storage.fetchone("SELECT COUNT(*) AS count FROM telegram_event_journal")
        count = int(row["count"]) if row else 0
        if count <= self.MAX_EVENTS:
            return
        excess = min(count - self.MAX_EVENTS, self.PRUNE_BATCH)
        await self.storage.execute(
            "DELETE FROM telegram_event_journal WHERE id IN (SELECT id FROM telegram_event_journal ORDER BY id LIMIT ?)",
            (excess,),
        )
