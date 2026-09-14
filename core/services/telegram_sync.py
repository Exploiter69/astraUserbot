"""Resumable, bounded Telegram incremental synchronization."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


SYNCED = "SYNCED"
RUNNING = "RUNNING"
GAP_DETECTED = "GAP_DETECTED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SyncCursor:
    peer_key: str
    last_message_id: int | None
    last_synced_at: float
    sync_state: str
    gap_detected: bool


@dataclass(frozen=True, slots=True)
class SyncResult:
    peer_key: str
    fetched: int
    last_message_id: int | None
    gap_detected: bool
    state: str


class TelegramIncrementalSync:
    """Bounded message synchronization backed by the existing Telegram facade.

    The facade remains the only Telegram transport boundary. Cursor state lives
    in the existing telegram_dialogs table so restart recovery does not require
    a second persistence system.
    """

    def __init__(self, telegram: Any, storage: Any, *, max_batch: int = 100) -> None:
        self.telegram = telegram
        self.storage = storage
        self.max_batch = max(1, int(max_batch))

    @staticmethod
    def peer_key(peer: Any) -> str:
        entity_id = getattr(peer, "id", None)
        if entity_id is not None:
            return f"id:{entity_id}"
        if isinstance(peer, int):
            return f"id:{peer}"
        if isinstance(peer, str):
            return f"username:{peer.strip().lower().lstrip('@')}"
        return f"value:{str(peer).strip().lower()}"

    async def cursor(self, peer: Any) -> SyncCursor | None:
        key = self.peer_key(peer)
        row = await self.storage.fetchone(
            """SELECT last_message_id, last_sync_at, sync_state
               FROM telegram_dialogs WHERE peer_key=?""",
            (key,),
        )
        if row is None:
            return None
        state = str(row[2])
        return SyncCursor(
            peer_key=key,
            last_message_id=int(row[0]) if row[0] is not None else None,
            last_synced_at=float(row[1]),
            sync_state=state,
            gap_detected=state == GAP_DETECTED,
        )

    async def sync(self, peer: Any, *, limit: int | None = None) -> SyncResult:
        cap = max(1, min(int(limit or self.max_batch), self.max_batch))
        key = self.peer_key(peer)
        previous = await self.cursor(peer)
        gap = bool(previous and previous.sync_state in {RUNNING, FAILED, GAP_DETECTED})
        previous_id = previous.last_message_id if previous else None

        await self._mark_running(peer, previous)
        try:
            kwargs: dict[str, Any] = {"limit": cap}
            if previous_id is not None:
                kwargs["min_id"] = previous_id
            messages = await self.telegram._call(
                "get_messages",
                peer,
                operation_class="READ",
                priority=3,
                **kwargs,
            )
            messages = list(messages or [])
            message_ids = sorted(
                {int(message.id) for message in messages if getattr(message, "id", None) is not None}
            )
            newest = max(message_ids) if message_ids else previous_id
            now = time.time()
            await self._write_cursor(peer, newest, now, SYNCED)
            return SyncResult(key, len(messages), newest, gap, SYNCED)
        except Exception:
            await self._write_cursor(peer, previous_id, time.time(), FAILED)
            raise

    async def _mark_running(self, peer: Any, previous: SyncCursor | None) -> None:
        key = self.peer_key(peer)
        if previous is None:
            await self.storage.execute(
                """INSERT INTO telegram_dialogs
                   (peer_key, dialog_type, title, username, last_message_id, last_sync_at, sync_state)
                   VALUES (?, 'SYNC_CURSOR', NULL, NULL, NULL, ?, ?)""",
                (key, time.time(), RUNNING),
            )
        else:
            await self.storage.execute(
                "UPDATE telegram_dialogs SET last_sync_at=?, sync_state=? WHERE peer_key=?",
                (time.time(), RUNNING, key),
            )

    async def _write_cursor(self, peer: Any, message_id: int | None, synced_at: float, state: str) -> None:
        key = self.peer_key(peer)
        await self.storage.execute(
            """UPDATE telegram_dialogs
               SET last_message_id=?, last_sync_at=?, sync_state=?
               WHERE peer_key=?""",
            (message_id, synced_at, state, key),
        )
