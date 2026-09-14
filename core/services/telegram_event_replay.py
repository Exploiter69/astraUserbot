"""Durable, bounded replay of Telegram event projections."""

from __future__ import annotations

import asyncio
import time
import uuid

from core.services.storage import StorageService
from core.services.telegram_event_journal import TelegramEventJournal
from core.services.telegram_event_projections import TelegramEventProjections


class TelegramEventReplay:
    """Rebuild selected Telegram projections in resumable bounded batches."""

    MAX_BATCH = 500
    PROJECTION = "telegram"

    def __init__(self, storage: StorageService, journal: TelegramEventJournal, projections: TelegramEventProjections) -> None:
        self.storage = storage
        self.journal = journal
        self.projections = projections
        self._started = False
        self._cancelled = False

    async def start(self) -> None:
        if self._started:
            return
        await self.storage.fetchone("SELECT 1 FROM telegram_replay_runs LIMIT 1")
        self._started = True

    async def close(self) -> None:
        self._cancelled = True
        self._started = False

    async def begin(self, *, projection: str = PROJECTION) -> str:
        self._require_started()
        if projection != self.PROJECTION:
            raise ValueError(f"Unsupported projection: {projection}")
        run_id = uuid.uuid4().hex
        now = time.time()
        await self.storage.transaction([
            ("DELETE FROM telegram_latest_messages", ()),
            ("DELETE FROM telegram_entity_observations", ()),
            ("DELETE FROM telegram_timeline", ()),
            ("INSERT INTO telegram_replay_runs(run_id,projection,state,cursor_id,processed_count,started_at,updated_at,last_error) VALUES (?,?,?,0,0,?,?,NULL)",
             (run_id, projection, "RUNNING", now, now)),
        ])
        self._cancelled = False
        return run_id

    async def replay(self, run_id: str, *, batch_size: int = MAX_BATCH) -> dict[str, int | str]:
        self._require_started()
        bounded = max(1, min(int(batch_size), self.MAX_BATCH))
        run = await self._get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown replay run: {run_id}")
        if run["state"] == "COMPLETED":
            return self._summary(run)
        if run["state"] == "FAILED":
            raise RuntimeError(f"Replay run failed: {run['last_error'] or 'unknown error'}")
        if run["state"] not in {"RUNNING", "PAUSED"}:
            raise RuntimeError(f"Replay run is not resumable: {run['state']}")
        await self.storage.execute("UPDATE telegram_replay_runs SET state='RUNNING', updated_at=? WHERE run_id=?", (time.time(), run_id))
        self._cancelled = False

        while not self._cancelled:
            cursor = int((await self._get_run(run_id))["cursor_id"])
            rows = await self.storage.fetchall(
                "SELECT * FROM telegram_event_journal WHERE id>? ORDER BY id LIMIT ?",
                (cursor, bounded),
            )
            if not rows:
                await self.storage.execute(
                    "UPDATE telegram_replay_runs SET state='COMPLETED', updated_at=? WHERE run_id=?",
                    (time.time(), run_id),
                )
                break
            for row in rows:
                await self.projections.apply_row(row)
                await self.storage.execute(
                    "UPDATE telegram_replay_runs SET cursor_id=?, processed_count=processed_count+1, updated_at=? WHERE run_id=? AND state='RUNNING'",
                    (int(row["id"]), time.time(), run_id),
                )
                if self._cancelled:
                    break
            await asyncio.sleep(0)

        if self._cancelled:
            await self.storage.execute(
                "UPDATE telegram_replay_runs SET state='PAUSED', updated_at=? WHERE run_id=? AND state='RUNNING'",
                (time.time(), run_id),
            )
        return self._summary(await self._get_run(run_id))

    async def resume(self, run_id: str, *, batch_size: int = MAX_BATCH) -> dict[str, int | str]:
        return await self.replay(run_id, batch_size=batch_size)

    async def status(self, run_id: str) -> dict[str, int | str]:
        self._require_started()
        run = await self._get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown replay run: {run_id}")
        return self._summary(run)

    async def cancel(self) -> None:
        self._cancelled = True

    async def _get_run(self, run_id: str) -> dict | None:
        row = await self.storage.fetchone("SELECT * FROM telegram_replay_runs WHERE run_id=?", (run_id,))
        return dict(row) if row else None

    @staticmethod
    def _summary(run: dict | None) -> dict[str, int | str]:
        if run is None:
            raise KeyError("Replay run no longer exists")
        return {
            "run_id": str(run["run_id"]),
            "projection": str(run["projection"]),
            "state": str(run["state"]),
            "cursor_id": int(run["cursor_id"]),
            "processed_count": int(run["processed_count"]),
        }

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("TelegramEventReplay is not started")
