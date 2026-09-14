"""Durable SQLite-backed job engine with leases, retries, fencing and recovery."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
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
    UNCERTAIN = "UNCERTAIN"
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

    MAX_PAYLOAD_BYTES = 1 * 1024 * 1024
    MAX_RESULT_BYTES = 2 * 1024 * 1024
    MAX_JOB_TYPE_CHARS = 128
    MAX_OWNER_CHARS = 256
    MAX_RESOURCE_CLASS_CHARS = 64
    MAX_IDEMPOTENCY_KEY_CHARS = 256
    MAX_ERROR_MESSAGE_CHARS = 500
    DEFAULT_RETENTION_SECONDS = 30 * 24 * 60 * 60
    CLEANUP_INTERVAL_SECONDS = 60 * 60

    def __init__(
        self,
        storage: StorageService,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
        poll_seconds: float = 1.0,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
    ) -> None:
        self.storage = storage
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self.lease_seconds = max(5.0, lease_seconds)
        self.poll_seconds = max(0.1, poll_seconds)
        self.retention_seconds = max(0.0, retention_seconds)
        self.handlers: dict[str, Handler] = {}
        self._worker_task: asyncio.Task[None] | None = None
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}
        self._stop = asyncio.Event()
        self._started = False
        self._last_cleanup = 0.0

    async def start(self) -> None:
        if self._started:
            return
        await self.recover_expired()
        await self.cleanup()
        self._stop.clear()
        self._worker_task = asyncio.create_task(self._worker_loop(), name=f"jobs.worker.{self.worker_id}")
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        self._stop.set()
        active_ids = list(self._active_tasks)
        active_tasks = list(self._active_tasks.values())
        for task in active_tasks:
            task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        await self._mark_active_uncertain(active_ids, reason="worker_shutdown")
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
        if not job_type or len(job_type) > self.MAX_JOB_TYPE_CHARS or job_type in self.handlers:
            raise ValueError(f"Job handler already registered: {job_type}")
        if not callable(handler):
            raise TypeError("Job handler must be callable")
        self.handlers[job_type] = handler

    async def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any] | None = None,
        *,
        owner: str | None = None,
        parent_id: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        priority: int = 0,
        resource_class: str = "default",
        delay: float = 0.0,
        verify_required: bool = False,
    ) -> Job:
        if not job_type or len(job_type) > self.MAX_JOB_TYPE_CHARS:
            raise ValueError("Invalid job type")
        if owner is not None and len(owner) > self.MAX_OWNER_CHARS:
            raise ValueError("Job owner is too long")
        if resource_class and len(resource_class) > self.MAX_RESOURCE_CLASS_CHARS:
            raise ValueError("Job resource class is too long")
        if idempotency_key is not None and len(idempotency_key) > self.MAX_IDEMPOTENCY_KEY_CHARS:
            raise ValueError("Job idempotency key is too long")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("Job payload must be an object")
        now = time.time()
        job_id = uuid.uuid4().hex
        payload_json = json.dumps(payload or {}, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        if len(payload_json.encode("utf-8")) > self.MAX_PAYLOAD_BYTES:
            raise ValueError("Job payload exceeds the configured size limit")
        async with self.storage.lock:
            assert self.storage.conn is not None
            if idempotency_key:
                async with self.storage.conn.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)) as cursor:
                    row = await cursor.fetchone()
                if row:
                    return self._row_to_job(row)
            try:
                await self.storage.conn.execute(
                    "INSERT INTO jobs(id,type,state,payload_json,owner,parent_id,idempotency_key,resource_class,priority,created_at,updated_at,available_at,max_attempts,verify_required) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id, job_type, JobState.QUEUED.value, payload_json, owner, parent_id,
                        idempotency_key, resource_class, priority, now, now, now + max(0.0, delay),
                        max(1, max_attempts), int(verify_required),
                    ),
                )
            except sqlite3.IntegrityError:
                if not idempotency_key:
                    raise
                async with self.storage.conn.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    raise
                return self._row_to_job(row)
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
            rows = await self.storage.fetchall(
                f"SELECT * FROM jobs WHERE state IN ({placeholders}) ORDER BY priority DESC, created_at LIMIT ?",
                tuple(s.value for s in states) + (limit,),
            )
        else:
            rows = await self.storage.fetchall("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row_to_job(row) for row in rows]

    async def claim(self, job_types: tuple[str, ...] | None = None) -> Job | None:
        now = time.time()
        expiry = now + self.lease_seconds
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute("BEGIN IMMEDIATE")
            try:
                if job_types is not None and not job_types:
                    await self.storage.conn.rollback()
                    return None
                if job_types is None:
                    query = "SELECT * FROM jobs WHERE state=? AND available_at<=? ORDER BY priority DESC, created_at LIMIT 1"
                    params: tuple[Any, ...] = (JobState.QUEUED.value, now)
                else:
                    placeholders = ",".join("?" for _ in job_types)
                    query = f"SELECT * FROM jobs WHERE state=? AND available_at<=? AND type IN ({placeholders}) ORDER BY priority DESC, created_at LIMIT 1"
                    params = (JobState.QUEUED.value, now, *job_types)
                async with self.storage.conn.execute(query, params) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    await self.storage.conn.rollback()
                    return None
                job_id = row["id"]
                cur = await self.storage.conn.execute(
                    "UPDATE jobs SET state=?, started_at=COALESCE(started_at,?), updated_at=?, attempt_count=attempt_count+1 WHERE id=? AND state=?",
                    (JobState.RUNNING.value, now, now, job_id, JobState.QUEUED.value),
                )
                if cur.rowcount != 1:
                    await self.storage.conn.rollback()
                    return None
                attempt = int(row["attempt_count"]) + 1
                await self.storage.conn.execute(
                    "INSERT OR REPLACE INTO leases(job_id,worker_id,attempt,leased_at,heartbeat_at,expires_at) VALUES (?,?,?,?,?,?)",
                    (job_id, self.worker_id, attempt, now, now, expiry),
                )
                await self.storage.conn.execute(
                    "INSERT INTO job_attempts(job_id,attempt,state,started_at) VALUES (?,?,?,?)",
                    (job_id, attempt, "RUNNING", now),
                )
                await self._event_locked(job_id, "CLAIMED", {"worker_id": self.worker_id, "attempt": attempt})
                await self.storage.conn.commit()
                async with self.storage.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)) as cursor:
                    updated = await cursor.fetchone()
                return self._row_to_job(updated)
            except Exception:
                await self.storage.conn.rollback()
                raise

    async def heartbeat(self, job_id: str) -> bool:
        now = time.time()
        async with self.storage.lock:
            assert self.storage.conn is not None
            cur = await self.storage.conn.execute(
                "UPDATE leases SET heartbeat_at=?,expires_at=? WHERE job_id=? AND worker_id=? AND attempt=(SELECT attempt_count FROM jobs WHERE id=? AND state=?)",
                (now, now + self.lease_seconds, job_id, self.worker_id, job_id, JobState.RUNNING.value),
            )
            await self.storage.conn.commit()
            return cur.rowcount == 1

    async def update_progress(self, job_id: str, progress: float) -> None:
        value = max(0.0, min(1.0, float(progress)))
        await self.storage.execute(
            "UPDATE jobs SET progress=?,updated_at=? WHERE id=? AND state IN (?,?) AND EXISTS (SELECT 1 FROM leases WHERE job_id=? AND worker_id=? AND attempt=(SELECT attempt_count FROM jobs WHERE id=?))",
            (value, time.time(), job_id, JobState.RUNNING.value, JobState.VERIFYING.value, job_id, self.worker_id, job_id),
        )

    async def complete(self, job_id: str, result: Any = None) -> None:
        job = await self.get(job_id)
        await self._complete_claimed(job, result)

    async def _complete_claimed(self, job: Job, result: Any = None) -> bool:
        now = time.time()
        result_json = json.dumps(result, separators=(",", ":"), default=str, ensure_ascii=False) if result is not None else None
        if result_json is not None and len(result_json.encode("utf-8")) > self.MAX_RESULT_BYTES:
            raise ValueError("Job result exceeds the configured size limit")
        state = JobState.VERIFYING if job.verify_required else JobState.COMPLETED
        async with self.storage.lock:
            assert self.storage.conn is not None
            cur = await self.storage.conn.execute(
                "UPDATE jobs SET state=?,result_json=?,progress=1,updated_at=?,completed_at=? WHERE id=? AND state=? AND attempt_count=? AND EXISTS (SELECT 1 FROM leases WHERE job_id=? AND worker_id=? AND attempt=?)",
                (state.value, result_json, now, None if state == JobState.VERIFYING else now, job.id, JobState.RUNNING.value, job.attempt_count, job.id, self.worker_id, job.attempt_count),
            )
            if cur.rowcount != 1:
                await self.storage.conn.rollback()
                return False
            await self.storage.conn.execute("DELETE FROM leases WHERE job_id=? AND worker_id=? AND attempt=?", (job.id, self.worker_id, job.attempt_count))
            attempt_state = "COMPLETED" if state != JobState.VERIFYING else "VERIFYING"
            await self.storage.conn.execute(
                "UPDATE job_attempts SET state=?,finished_at=? WHERE job_id=? AND attempt=? AND state='RUNNING'",
                (attempt_state, now, job.id, job.attempt_count),
            )
            await self._event_locked(job.id, state.value, {"attempt": job.attempt_count})
            await self.storage.conn.commit()
            return True

    async def verify(self, job_id: str, ok: bool, message: str | None = None) -> None:
        now = time.time()
        state = JobState.COMPLETED if ok else JobState.FAILED
        error = None if ok else (message or "Verification failed")[: self.MAX_ERROR_MESSAGE_CHARS]
        async with self.storage.lock:
            assert self.storage.conn is not None
            cur = await self.storage.conn.execute(
                "UPDATE jobs SET state=?,error_code=?,error_message=?,completed_at=?,updated_at=? WHERE id=? AND state=?",
                (state.value, None if ok else "VERIFICATION_FAILED", error, now, now, job_id, JobState.VERIFYING.value),
            )
            if cur.rowcount != 1:
                await self.storage.conn.rollback()
                raise ValueError(f"Job is not verifying: {job_id}")
            await self._event_locked(job_id, state.value, {"verified": ok})
            await self.storage.conn.commit()

    async def cancel(self, job_id: str) -> None:
        job = await self.get(job_id)
        now = time.time()
        if job.state in {JobState.RUNNING, JobState.VERIFYING}:
            state = JobState.UNCERTAIN
            code = "CANCELLATION_UNCERTAIN"
            message = "Cancellation interrupted active work; external side effects must be verified before replay."
        elif job.state in {JobState.QUEUED, JobState.PAUSED}:
            state = JobState.CANCELLED
            code = None
            message = None
        else:
            return
        async with self.storage.lock:
            assert self.storage.conn is not None
            await self.storage.conn.execute(
                "UPDATE jobs SET state=?,error_code=?,error_message=?,updated_at=?,completed_at=? WHERE id=? AND state IN (?,?,?,?)",
                (state.value, code, message, now, now if state == JobState.CANCELLED else None, job_id, JobState.QUEUED.value, JobState.RUNNING.value, JobState.PAUSED.value, JobState.VERIFYING.value),
            )
            await self.storage.conn.execute("DELETE FROM leases WHERE job_id=?", (job_id,))
            await self._event_locked(job_id, "CANCELLED" if state == JobState.CANCELLED else "CANCELLED_UNCERTAIN", {})
            await self.storage.conn.commit()
        task = self._active_tasks.get(job_id)
        if task is not None:
            task.cancel()

    async def recover_expired(self) -> int:
        now = time.time()
        async with self.storage.lock:
            assert self.storage.conn is not None
            async with self.storage.conn.execute("SELECT job_id,worker_id,attempt FROM leases WHERE expires_at<?", (now,)) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                job_id = row["job_id"]
                cur = await self.storage.conn.execute(
                    "UPDATE jobs SET state=?,error_code=?,error_message=?,updated_at=? WHERE id=? AND state=? AND attempt_count=?",
                    (JobState.UNCERTAIN.value, "LEASE_EXPIRED", "Worker lease expired; execution outcome is unknown and requires verification before replay.", now, job_id, JobState.RUNNING.value, row["attempt"]),
                )
                await self.storage.conn.execute("DELETE FROM leases WHERE job_id=? AND worker_id=? AND attempt=?", (job_id, row["worker_id"], row["attempt"]))
                if cur.rowcount:
                    await self._event_locked(job_id, "LEASE_EXPIRED_UNCERTAIN", {"worker_id": row["worker_id"], "attempt": row["attempt"]})
            await self.storage.conn.commit()
            return len(rows)

    async def requeue_uncertain(self, job_id: str) -> Job:
        """Explicitly requeue a job after an operator verifies replay is safe."""
        now = time.time()
        async with self.storage.lock:
            assert self.storage.conn is not None
            cur = await self.storage.conn.execute(
                "UPDATE jobs SET state=?,error_code=NULL,error_message=NULL,available_at=?,updated_at=?,completed_at=NULL WHERE id=? AND state=?",
                (JobState.QUEUED.value, now, now, job_id, JobState.UNCERTAIN.value),
            )
            if cur.rowcount != 1:
                await self.storage.conn.rollback()
                raise ValueError(f"Job is not uncertain: {job_id}")
            await self._event_locked(job_id, "UNCERTAIN_REQUEUED", {"worker_id": self.worker_id})
            await self.storage.conn.commit()
        return await self.get(job_id)

    async def _mark_active_uncertain(self, job_ids: list[str], *, reason: str) -> None:
        if not job_ids:
            return
        now = time.time()
        async with self.storage.lock:
            assert self.storage.conn is not None
            for job_id in job_ids:
                await self.storage.conn.execute(
                    "UPDATE jobs SET state=?,error_code=?,error_message=?,updated_at=? WHERE id=? AND state=?",
                    (JobState.UNCERTAIN.value, "WORKER_SHUTDOWN", "Worker stopped while job was active; execution outcome is unknown and requires verification before replay.", now, job_id, JobState.RUNNING.value),
                )
                await self.storage.conn.execute("DELETE FROM leases WHERE job_id=?", (job_id,))
                await self._event_locked(job_id, "WORKER_SHUTDOWN_UNCERTAIN", {"reason": reason})
            await self.storage.conn.commit()

    async def fail(self, job_id: str, code: str, message: str, *, retryable: bool = False) -> None:
        job = await self.get(job_id)
        await self._fail_claimed(job, code, message, retryable=retryable)

    async def _fail_claimed(self, job: Job, code: str, message: str, *, retryable: bool = False) -> bool:
        now = time.time()
        should_retry = retryable and job.attempt_count < job.max_attempts
        state = JobState.QUEUED if should_retry else JobState.FAILED
        delay = min(300.0, 2 ** max(0, job.attempt_count - 1)) if should_retry else 0.0
        bounded_message = str(message)[: self.MAX_ERROR_MESSAGE_CHARS]
        async with self.storage.lock:
            assert self.storage.conn is not None
            cur = await self.storage.conn.execute(
                "UPDATE jobs SET state=?,error_code=?,error_message=?,available_at=?,updated_at=?,completed_at=? WHERE id=? AND state=? AND attempt_count=? AND EXISTS (SELECT 1 FROM leases WHERE job_id=? AND worker_id=? AND attempt=?)",
                (state.value, str(code)[:128], bounded_message, now + delay, now, None if should_retry else now, job.id, JobState.RUNNING.value, job.attempt_count, job.id, self.worker_id, job.attempt_count),
            )
            if cur.rowcount != 1:
                await self.storage.conn.rollback()
                return False
            await self.storage.conn.execute("DELETE FROM leases WHERE job_id=? AND worker_id=? AND attempt=?", (job.id, self.worker_id, job.attempt_count))
            await self.storage.conn.execute(
                "UPDATE job_attempts SET state='FAILED',finished_at=?,error_code=?,error_message=? WHERE job_id=? AND attempt=? AND state='RUNNING'",
                (now, str(code)[:128], bounded_message, job.id, job.attempt_count),
            )
            await self._event_locked(job.id, "RETRY_SCHEDULED" if should_retry else "FAILED", {"retryable": retryable, "attempt": job.attempt_count, "next_attempt": job.attempt_count + 1 if should_retry else None})
            await self.storage.conn.commit()
            return True

    async def cleanup(self, *, retention_seconds: float | None = None, now: float | None = None) -> dict[str, int]:
        retention = self.retention_seconds if retention_seconds is None else max(0.0, retention_seconds)
        cutoff = (time.time() if now is None else now) - retention
        terminal = tuple(state.value for state in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED))
        placeholders = ",".join("?" for _ in terminal)
        async with self.storage.lock:
            assert self.storage.conn is not None
            cur = await self.storage.conn.execute(
                f"DELETE FROM jobs WHERE state IN ({placeholders}) AND COALESCE(completed_at,updated_at)<? AND NOT EXISTS (SELECT 1 FROM leases WHERE leases.job_id=jobs.id)",
                terminal + (cutoff,),
            )
            await self.storage.conn.commit()
            self._last_cleanup = time.time()
            return {"jobs_deleted": max(0, cur.rowcount)}

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
                await self._complete_claimed(current, result)
        except asyncio.CancelledError:
            return
        except JobError as exc:
            await self._fail_claimed(job, exc.code, str(exc), retryable=exc.retryable)
        except Exception:
            logger.exception("Durable job failed id=%s type=%s", job.id, job.type)
            await self._fail_claimed(job, "UNEXPECTED_FAILURE", "Job execution failed", retryable=False)
        finally:
            self._active_tasks.pop(job.id, None)

    async def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = await self.claim(tuple(self.handlers))
                if job is None:
                    if time.time() - self._last_cleanup >= self.CLEANUP_INTERVAL_SECONDS:
                        await self.recover_expired()
                        await self.cleanup()
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                    except asyncio.TimeoutError:
                        pass
                    continue
                handler = self.handlers.get(job.type)
                if handler is None:
                    logger.warning("Job handler disappeared after claim type=%s id=%s", job.type, job.id)
                    await self._fail_claimed(job, "NO_HANDLER", f"No handler registered for {job.type}", retryable=False)
                    continue
                task = asyncio.create_task(self._run_job(job, handler), name=f"jobs.execute.{job.id}")
                self._active_tasks[job.id] = task
                await task
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Job worker loop failure")
                await asyncio.sleep(self.poll_seconds)

    async def _event_locked(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        assert self.storage.conn is not None
        await self.storage.conn.execute(
            "INSERT INTO job_events(job_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
            (job_id, event_type, json.dumps(payload, separators=(",", ":")), time.time()),
        )

    def _row_to_job(self, row: Any) -> Job:
        return Job(
            id=row["id"], type=row["type"], state=JobState(row["state"]),
            payload=json.loads(row["payload_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_code=row["error_code"], error_message=row["error_message"], owner=row["owner"],
            parent_id=row["parent_id"], attempt_count=int(row["attempt_count"]), max_attempts=int(row["max_attempts"]),
            progress=float(row["progress"]), resource_class=row["resource_class"], priority=int(row["priority"]),
            verify_required=bool(row["verify_required"]),
        )