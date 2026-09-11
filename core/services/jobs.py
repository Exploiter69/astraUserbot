"""Durable SQLite-backed job engine with leases, retries and recovery."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable

from core.services.storage import StorageService

logger = logging.getLogger("astra.jobs")


class JobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobError(RuntimeError):
    """Controlled job failure with a stable retry classification."""

    def __init__(self, message: str, code: str = "JOB_FAILED", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class Job:
    id: str
    type: str
    state: JobState
    payload: dict[str, Any]
    result: Any
    error_code: str | None
    error_message: str | None
    owner: str | None
    parent_id: str | None
    attempt_count: int
    max_attempts: int
    progress: float
    resource_class: str
    priority: int
    verify_required: bool


Handler = Callable[[Job], Awaitable[Any]]


class JobEngine:
    """Own accepted durable work; workers may disappear without losing job state."""

    def __init__(self, storage: StorageService, *, worker_id: str | None = None, lease_seconds: float = 60.0, poll_seconds: float = 1.0) -> None:
        self.storage = storage
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self.lease_seconds = max(5.0, lease_seconds)
        self.poll_seconds = max(0.1, poll_seconds)
        self.handlers: dict[str, Handler] = {}
        self._worker_task: asyncio.Task[None] | None = None
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}
        self._stop = asyncio.Event()
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.recover_expired()
        self._stop.clear()
        self._worker_task = asyncio.create_task(self._worker_loop(), name=f"jobs.worker.{self.worker_id}")
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        self._stop.set()
        for task in list(self._active_tasks.values()):
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._worker_task = None
        self._active_tasks.clear()
        self._started = False

    def register_handler(self, job_type: str, handler: Handler) -> None:
        if not job_type or job_type in self.handlers:
            raise ValueError(f"Job handler already registered: {job_type}")
        self.handlers[job_type] = handler

    async def enqueue(self, job_type: str, payload: dict[str, Any] | None = None, *, owner: str | None = None, parent_id: str | None = None, idempotency_key: str | None = None, max_attempts: int = 3, priority: int = 0, resource_class: str = "default", delay: float = 0.0, verify_required: bool = False) -> Job:
        now = time.time()
        job_id = uuid.uuid4().hex
        payload_json = json.dumps(payload or {}, separators=(",", ":"), sort_keys=True)
        async with self.storage.lock:
            assert self.storage.conn is not None
            if idempotency_key:
                async with self.storage.conn.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)) as cursor:
                    row = await cursor.fetchone()
                if row:
                    return self._row_to_job(row)
            await self.storage.conn.execute("INSERT INTO jobs(id,type,state,payload_json,owner,parent_id,idempotency_key,resource_class,priority,created_at,updated_at,available_at,max_attempts,verify_required) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, job_type, JobState.QUEUED.value, payload_json, owner, parent_id, idempotency_key, resource_class, priority, now, now, now + max(0.0, delay), max(1, max_attempts), int(verify_required)))
            await self._event_locked(job_id, "ENQUEUED", {"type": job_type})
            await self.storage.conn.commit()
        return await self.get(job_id)

    async def get(self, job_id: str) -> Job:
        row = await self.storage.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))
        if row is None:
            raise KeyError(job_id)
        return self._row_to_job(row)

    async def list(self, *, states: tuple[JobState, ...] | None = None, limit: int = 100) -> list[Job]:
        limit = max(1, min(limit, 1000))
        if states:
            placeholders = ",".join("?" for _ in states)
            rows = await self.storage.fetchall(f"SELECT * FROM jobs WHERE state IN ({placeholders}) ORDER BY priority DESC, created_at LIMIT ?", tuple(s.value for s in states) + (limit,))
        else:
            rows = await self.storage.fetchall("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row_to_job(row) for row in rows]

    async def claim(self) -> Job | None:
        now = time.time()
        expiry = now + self.lease_seconds
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute("BEGIN IMMEDIATE")
            async with self.storage.conn.execute("SELECT * FROM jobs WHERE state=? AND available_at<=? ORDER BY priority DESC, created_at LIMIT 1", (JobState.QUEUED.value, now)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                await self.storage.conn.rollback()
                return None
            job_id = row["id"]
            cur = await self.storage.conn.execute("UPDATE jobs SET state=?, started_at=COALESCE(started_at,?), updated_at=?, attempt_count=attempt_count+1 WHERE id=? AND state=?", (JobState.RUNNING.value, now, now, job_id, JobState.QUEUED.value))
            if cur.rowcount != 1:
                await self.storage.conn.rollback()
                return None
            await self.storage.conn.execute("INSERT OR REPLACE INTO leases(job_id,worker_id,leased_at,heartbeat_at,expires_at) VALUES (?,?,?,?,?)", (job_id, self.worker_id, now, now, expiry))
            await self.storage.conn.execute("INSERT INTO job_attempts(job_id,attempt,state,started_at) SELECT id,attempt_count,'RUNNING',? FROM jobs WHERE id=?", (now, job_id))
            await self._event_locked(job_id, "CLAIMED", {"worker_id": self.worker_id})
            await self.storage.conn.commit()
            async with self.storage.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)) as cursor:
                updated = await cursor.fetchone()
            return self._row_to_job(updated)

    async def heartbeat(self, job_id: str) -> bool:
        now = time.time()
        async with self.storage.lock:
            assert self.storage.conn is not None
            cur = await self.storage.conn.execute("UPDATE leases SET heartbeat_at=?,expires_at=? WHERE job_id=? AND worker_id=?", (now, now + self.lease_seconds, job_id, self.worker_id))
            await self.storage.conn.commit()
            return cur.rowcount == 1

    async def update_progress(self, job_id: str, progress: float) -> None:
        value = max(0.0, min(1.0, float(progress)))
        await self.storage.execute("UPDATE jobs SET progress=?,updated_at=? WHERE id=? AND state IN (?,?)", (value, time.time(), job_id, JobState.RUNNING.value, JobState.VERIFYING.value))

    async def complete(self, job_id: str, result: Any = None) -> None:
        now = time.time()
        state = JobState.VERIFYING if (await self.get(job_id)).verify_required else JobState.COMPLETED
        result_json = json.dumps(result, separators=(",", ":"), default=str) if result is not None else None
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute("UPDATE jobs SET state=?,result_json=?,progress=1,updated_at=?,completed_at=? WHERE id=? AND state=?", (state.value, result_json, now, None if state == JobState.VERIFYING else now, job_id, JobState.RUNNING.value))
            await self.storage.conn.execute("DELETE FROM leases WHERE job_id=?", (job_id,))
            await self.storage.conn.execute("UPDATE job_attempts SET state='COMPLETED',finished_at=? WHERE job_id=? AND attempt=(SELECT attempt_count FROM jobs WHERE id=?)", (now, job_id, job_id))
            await self._event_locked(job_id, state.value, {})
            await self.storage.conn.commit()

    async def verify(self, job_id: str, ok: bool, message: str | None = None) -> None:
        now = time.time()
        state = JobState.COMPLETED if ok else JobState.FAILED
        await self.storage.execute("UPDATE jobs SET state=?,error_code=?,error_message=?,completed_at=?,updated_at=? WHERE id=? AND state=?", (state.value, None if ok else "VERIFICATION_FAILED", None if ok else (message or "Verification failed"), now, now, job_id, JobState.VERIFYING.value))
        await self.storage.execute("INSERT INTO job_events(job_id,event_type,payload_json,created_at) VALUES (?,?,?,?)", (job_id, state.value, json.dumps({}), now))

    async def cancel(self, job_id: str) -> None:
        now = time.time()
        await self.get(job_id)
        await self.storage.execute("UPDATE jobs SET state=?,updated_at=?,completed_at=? WHERE id=? AND state IN (?,?,?,?)", (JobState.CANCELLED.value, now, now, job_id, JobState.QUEUED.value, JobState.RUNNING.value, JobState.PAUSED.value, JobState.VERIFYING.value))
        await self.storage.execute("DELETE FROM leases WHERE job_id=?", (job_id,))
        task = self._active_tasks.get(job_id)
        if task is not None:
            task.cancel()
        await self.storage.execute("INSERT INTO job_events(job_id,event_type,payload_json,created_at) VALUES (?,?,?,?)", (job_id, "CANCELLED", "{}", now))

    async def recover_expired(self) -> int:
        now = time.time()
        async with self.storage.lock:
            assert self.storage.conn is not None
            rows = await self.storage.fetchall("SELECT job_id FROM leases WHERE expires_at<?", (now,))
            for row in rows:
                await self.storage.conn.execute("UPDATE jobs SET state=?,available_at=?,updated_at=? WHERE id=? AND state=?", (JobState.QUEUED.value, now, now, row[0], JobState.RUNNING.value))
                await self.storage.conn.execute("DELETE FROM leases WHERE job_id=?", (row[0],))
                await self._event_locked(row[0], "LEASE_EXPIRED", {})
            await self.storage.conn.commit()
            return len(rows)

    async def fail(self, job_id: str, code: str, message: str, *, retryable: bool = False) -> None:
        job = await self.get(job_id)
        now = time.time()
        should_retry = retryable and job.attempt_count < job.max_attempts
        state = JobState.QUEUED if should_retry else JobState.FAILED
        delay = min(300.0, 2 ** max(0, job.attempt_count - 1)) if should_retry else 0.0
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute("UPDATE jobs SET state=?,error_code=?,error_message=?,available_at=?,updated_at=?,completed_at=? WHERE id=? AND state=?", (state.value, code, message[:500], now + delay, now, None if should_retry else now, job_id, JobState.RUNNING.value))
            await self.storage.conn.execute("DELETE FROM leases WHERE job_id=?", (job_id,))
            await self.storage.conn.execute("UPDATE job_attempts SET state='FAILED',finished_at=?,error_code=?,error_message=? WHERE job_id=? AND attempt=(SELECT attempt_count FROM jobs WHERE id=?)", (now, code, message[:500], job_id, job_id))
            await self._event_locked(job_id, "RETRY_SCHEDULED" if should_retry else "FAILED", {"retryable": retryable})
            await self.storage.conn.commit()

    async def _execute_handler(self, job: Job, handler: Handler) -> Any:
        async def lease_loop() -> None:
            interval = max(1.0, self.lease_seconds / 3.0)
            while True:
                await asyncio.sleep(interval)
                if not await self.heartbeat(job.id):
                    return

        heartbeat_task = asyncio.create_task(lease_loop(), name=f"jobs.heartbeat.{job.id}")
        try:
            return await handler(job)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _run_job(self, job: Job, handler: Handler) -> None:
        try:
            result = await self._execute_handler(job, handler)
            current = await self.get(job.id)
            if current.state == JobState.RUNNING:
                await self.complete(job.id, result)
        except asyncio.CancelledError:
            return
        except JobError as exc:
            await self.fail(job.id, exc.code, str(exc)[:500], retryable=exc.retryable)
        except Exception:
            logger.exception("Durable job failed id=%s type=%s", job.id, job.type)
            await self.fail(job.id, "UNEXPECTED_FAILURE", "Job execution failed", retryable=False)
        finally:
            self._active_tasks.pop(job.id, None)

    async def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = await self.claim()
                if job is None:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                    continue
                handler = self.handlers.get(job.type)
                if handler is None:
                    await self.fail(job.id, "NO_HANDLER", f"No handler registered for {job.type}")
                    continue
                task = asyncio.create_task(self._run_job(job, handler), name=f"jobs.execute.{job.id}")
                self._active_tasks[job.id] = task
                await task
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Job worker loop failure")
                await asyncio.sleep(self.poll_seconds)

    async def _event_locked(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        assert self.storage.conn is not None
        await self.storage.conn.execute("INSERT INTO job_events(job_id,event_type,payload_json,created_at) VALUES (?,?,?,?)", (job_id, event_type, json.dumps(payload, separators=(",", ":"), default=str), time.time()))

    @staticmethod
    def _row_to_job(row: Any) -> Job:
        return Job(id=row["id"], type=row["type"], state=JobState(row["state"]), payload=json.loads(row["payload_json"]), result=json.loads(row["result_json"]) if row["result_json"] else None, error_code=row["error_code"], error_message=row["error_message"], owner=row["owner"], parent_id=row["parent_id"], attempt_count=row["attempt_count"], max_attempts=row["max_attempts"], progress=row["progress"], resource_class=row["resource_class"], priority=row["priority"], verify_required=bool(row["verify_required"]))
