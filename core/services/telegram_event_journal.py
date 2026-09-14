"""Durable, bounded SQLite journal for normalized Telegram events."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from core.services.storage import StorageService
from core.services.telegram_events import TelegramEvent


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
        await self.storage.fetchone("SELECT 1 FROM telegram_event_journal LIMIT 1")
        # A process crash can leave a claimed event in PROCESSING. Projection
        # operations are idempotent, so make interrupted work retryable on restart.
        await self.storage.execute(
            "UPDATE telegram_event_journal SET processing_state='PENDING' WHERE processing_state='PROCESSING'"
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
                (event.event_id, fingerprint, event.event_type, event.observed_at, event.source_peer,
                 event.message_id, event.entity_id, payload, event.schema_version, now),
            )
        except Exception as exc:
            if "UNIQUE constraint failed: telegram_event_journal.fingerprint" in str(exc):
                return False
            raise
        await self._prune()
        return True

    async def get(self, event_id: str) -> dict[str, Any] | None:
        row = await self.storage.fetchone("SELECT * FROM telegram_event_journal WHERE event_id=?", (event_id,))
        return dict(row) if row else None

    async def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return pending and previously failed events in FIFO order."""
        bounded = max(1, min(int(limit), 1000))
        rows = await self.storage.fetchall(
            "SELECT * FROM telegram_event_journal WHERE processing_state IN ('PENDING', 'FAILED') ORDER BY id LIMIT ?",
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
        cursor = await self.storage.execute(
            """
            UPDATE telegram_event_journal
            SET processing_state='FAILED', last_error=?
            WHERE event_id=? AND processing_state='PROCESSING'
            """,
            (str(error)[:1024], event_id),
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
