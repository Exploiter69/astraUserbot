from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.services.jobs import JobEngine, JobError, JobState, ReconcileOutcome
from core.services.send_jobs import (
    AuthoritativeSendRejection,
    SEND_EFFECT_CLASS,
    SEND_JOB_TYPE,
    SendJobAdapter,
    send_fingerprint,
)
from core.services.storage import StorageService


@dataclass
class FakeMessage:
    id: int
    sender_id: int
    message: str
    date: datetime


class FakeTelegram:
    def __init__(self):
        self.client = self
        self.sent = []
        self.history = []
        self.send_behavior = None
        self.history_error = None
        self.history_wait = None

    async def get_me(self):
        return SimpleNamespace(id=42)

    async def send_message(self, target, text):
        self.sent.append((target, text))
        if self.send_behavior is not None:
            return await self.send_behavior(target, text)
        message = FakeMessage(
            id=len(self.sent),
            sender_id=42,
            message=text,
            date=datetime.now(timezone.utc),
        )
        self.history.insert(0, message)
        return message

    async def get_messages(self, target, *, limit=100):
        if self.history_wait is not None:
            await self.history_wait.wait()
        if self.history_error is not None:
            raise self.history_error
        return list(self.history[:limit])


async def make_services(tmp_path):
    storage = StorageService(tmp_path)
    await storage.start()
    jobs = JobEngine(storage, worker_id="send-reconcile-test", poll_seconds=0.01)
    telegram = FakeTelegram()
    adapter = SendJobAdapter(jobs, telegram, storage)
    return storage, jobs, telegram, adapter


async def mark_uncertain(storage, job_id):
    await storage.execute(
        "UPDATE jobs SET state=?, attempt_count=1, started_at=? WHERE id=?",
        (JobState.UNCERTAIN.value, time.time() - 1, job_id),
    )


@pytest.mark.asyncio
async def test_send_happened_recorded_message_id_completes_without_resend(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(SEND_JOB_TYPE, {"target": "chat-1", "text": "hello"})
        await adapter.handle(job)
        await mark_uncertain(storage, job.id)

        result = await jobs.requeue_uncertain(job.id)

        assert result.state == JobState.COMPLETED
        assert len(telegram.sent) == 1
        assert telegram.sent == [("chat-1", "hello")]
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_send_not_happened_authoritative_rejection_allows_one_reexecution(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(SEND_JOB_TYPE, {"target": "chat-1", "text": "hello"})

        async def reject_once(_target, _text):
            telegram.send_behavior = None
            raise AuthoritativeSendRejection("fake authoritative rejection")

        telegram.send_behavior = reject_once
        first = await jobs.claim()
        assert first is not None
        with pytest.raises(JobError) as failure:
            await adapter.handle(first)
        assert failure.value.code == "SEND_REJECTED"
        assert await jobs._fail_claimed(
            first, failure.value.code, str(failure.value), retryable=True
        )
        assert (await jobs.get(job.id)).state == JobState.UNCERTAIN

        requeued = await jobs.requeue_uncertain(job.id)
        assert requeued.state == JobState.QUEUED

        second = await jobs.claim()
        assert second is not None and second.id == job.id
        result = await adapter.handle(second)
        assert await jobs._complete_claimed(second, result)

        assert (await jobs.get(job.id)).state == JobState.COMPLETED
        assert len(telegram.sent) == 2
        assert telegram.sent == [("chat-1", "hello"), ("chat-1", "hello")]
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_match", "ambiguous", "history_unavailable", "timeout"])
async def test_send_unknown_stays_uncertain_and_never_replays(tmp_path, case):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(SEND_JOB_TYPE, {"target": "chat-1", "text": "hello"})
        started_at = time.time() - 1
        fingerprint = send_fingerprint("chat-1", 42, "hello")
        await adapter._record_attempt(job, "chat-1", fingerprint, started_at)
        await mark_uncertain(storage, job.id)

        if case == "ambiguous":
            timestamp = datetime.now(timezone.utc)
            telegram.history = [
                FakeMessage(101, 42, "hello", timestamp),
                FakeMessage(102, 42, "hello", timestamp),
            ]
        elif case == "history_unavailable":
            telegram.history_error = RuntimeError("history unavailable")
        elif case == "timeout":
            telegram.history_wait = asyncio.Event()
            jobs.RECONCILER_TIMEOUT_SECONDS = 0.02

        result = await jobs.requeue_uncertain(job.id)

        assert result.state == JobState.UNCERTAIN
        assert len(telegram.sent) == 0
        assert (await jobs.get(job.id)).state == JobState.UNCERTAIN
    finally:
        if telegram.history_wait is not None:
            telegram.history_wait.set()
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_send_multi_effect_happened_plus_unknown_remains_uncertain(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(SEND_JOB_TYPE, {"target": "chat-1", "text": "hello"})
        started_at = time.time() - 1
        fingerprint = send_fingerprint("chat-1", 42, "hello")
        await adapter._record_attempt(job, "chat-1", fingerprint, started_at)
        await storage.execute(
            """INSERT INTO job_effects(
                   effect_id, job_id, effect_class, state, required, updated_at,
                   target_json, payload_fingerprint, attempt_started_at
               ) VALUES (?, ?, ?, 'PENDING', 1, ?, ?, ?, ?)""",
            (
                "effect-unknown",
                job.id,
                SEND_EFFECT_CLASS,
                time.time(),
                json.dumps("chat-1"),
                "different-fingerprint",
                started_at,
            ),
        )
        telegram.history = [
            FakeMessage(200, 42, "hello", datetime.now(timezone.utc))
        ]
        await mark_uncertain(storage, job.id)

        result = await jobs.requeue_uncertain(job.id)

        assert result.state == JobState.UNCERTAIN
        effects = await storage.fetchall(
            "SELECT state FROM job_effects WHERE job_id=? AND required=1", (job.id,)
        )
        assert sorted(row["state"] for row in effects) == ["HAPPENED", "UNKNOWN"]
        assert telegram.sent == []
    finally:
        await jobs.close()
        await storage.close()
