from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.services.delete_jobs import (
    AuthoritativeDeleteRejection, DELETE_JOB_TYPE, DeleteJobAdapter,
)
from core.services.jobs import JobEngine, JobError, JobState
from core.services.storage import StorageService


@dataclass
class FakeMessage:
    id: int
    message: str
    sender_id: int = 42
    date: str = "2026-10-15T00:00:00Z"
    media: object | None = None


class FakeTelegram:
    def __init__(self):
        self.messages = {7: FakeMessage(7, "to-delete")}
        self.deletes = []
        self.delete_behavior = None
        self.history_error = None
        self.can_read = True
        self.can_delete = True
        self.duplicate_observation = False

    async def get_messages(self, target, *, limit=100, min_id=None, max_id=None):
        if self.history_error:
            raise self.history_error
        found = [
            message for mid, message in self.messages.items()
            if (min_id is None or mid > min_id) and (max_id is None or mid < max_id)
        ][:limit]
        if self.duplicate_observation and found:
            return found + [found[0]]
        return found

    async def get_capabilities(self, target, *, fresh=True):
        return {"can_read": self.can_read, "can_delete": self.can_delete}

    async def delete_messages(self, target, message_id):
        self.deletes.append((target, message_id))
        if self.delete_behavior is not None:
            return await self.delete_behavior(target, message_id)
        self.messages.pop(message_id, None)
        return True


async def make_services(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    jobs = JobEngine(storage, worker_id="delete-reconcile-test", poll_seconds=0.01)
    telegram = FakeTelegram()
    adapter = DeleteJobAdapter(jobs, telegram, storage)
    return storage, jobs, telegram, adapter


async def mark_uncertain(storage, job_id):
    await storage.execute(
        "UPDATE jobs SET state=?, attempt_count=1, started_at=? WHERE id=?",
        (JobState.UNCERTAIN.value, time.time() - 1, job_id),
    )


@pytest.mark.asyncio
async def test_delete_happened_confirmed_absence_completes_without_redelete(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(DELETE_JOB_TYPE, {"target": "chat-1", "message_id": 7})
        await adapter.handle(job)
        assert 7 not in telegram.messages
        await mark_uncertain(storage, job.id)
        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.COMPLETED
        assert telegram.deletes == [("chat-1", 7)]
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_delete_not_happened_authoritative_rejection_allows_one_retry(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(DELETE_JOB_TYPE, {"target": "chat-1", "message_id": 7})
        async def reject_once(target, message_id):
            telegram.delete_behavior = None
            raise AuthoritativeDeleteRejection("explicitly not applied")
        telegram.delete_behavior = reject_once
        claimed = await jobs.claim()
        assert claimed is not None
        with pytest.raises(JobError) as failure:
            await adapter.handle(claimed)
        assert failure.value.code == "DELETE_REJECTED"
        assert await jobs._fail_claimed(claimed, failure.value.code, str(failure.value), retryable=True)
        assert (await jobs.get(job.id)).state == JobState.UNCERTAIN

        assert (await jobs.requeue_uncertain(job.id)).state == JobState.QUEUED
        second = await jobs.claim()
        assert second is not None and second.id == job.id
        result = await adapter.handle(second)
        assert await jobs._complete_claimed(second, result)
        assert (await jobs.get(job.id)).state == JobState.COMPLETED
        assert telegram.deletes == [("chat-1", 7), ("chat-1", 7)]
        assert 7 not in telegram.messages
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "absence_unconfirmed", "history_unavailable", "conflicting_observation", "timeout",
])
async def test_delete_unknown_stays_uncertain_without_replay(tmp_path, case):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(DELETE_JOB_TYPE, {"target": "chat-1", "message_id": 7})
        claimed = await jobs.claim()
        assert claimed is not None
        await adapter._record_attempt(claimed, "chat-1", 7, telegram.messages[7], time.time() - 1)
        await mark_uncertain(storage, job.id)
        if case == "absence_unconfirmed":
            telegram.messages.clear()
            telegram.can_read = False
        elif case == "history_unavailable":
            telegram.messages.clear()
            telegram.history_error = RuntimeError("history/access unavailable")
        elif case == "conflicting_observation":
            telegram.duplicate_observation = True
        elif case == "timeout":
            jobs.RECONCILER_TIMEOUT_SECONDS = 0.02
            original = telegram.get_messages
            async def slow_get(*args, **kwargs):
                import asyncio
                await asyncio.sleep(1)
                return await original(*args, **kwargs)
            telegram.get_messages = slow_get

        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.UNCERTAIN
        assert telegram.deletes == []
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_delete_happened_does_not_complete_other_unknown_required_effect(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(DELETE_JOB_TYPE, {"target": "chat-1", "message_id": 7})
        claimed = await jobs.claim()
        assert claimed is not None
        await adapter._record_attempt(claimed, "chat-1", 7, telegram.messages[7], time.time() - 1)
        telegram.messages.clear()
        await storage.execute(
            """INSERT INTO job_effects(effect_id,job_id,effect_class,state,required,updated_at)
               VALUES ('effect-unknown', ?, 'OTHER', 'PENDING', 1, ?)""",
            (job.id, time.time()),
        )
        await mark_uncertain(storage, job.id)
        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.UNCERTAIN
        rows = await storage.fetchall(
            "SELECT state FROM job_effects WHERE job_id=? AND required=1", (job.id,)
        )
        assert sorted(row["state"] for row in rows) == ["HAPPENED", "UNKNOWN"]
        assert telegram.deletes == []
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_delete_rejection_without_delete_capability_stays_uncertain(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(DELETE_JOB_TYPE, {"target": "chat-1", "message_id": 7})
        async def reject(_target, _message_id):
            raise AuthoritativeDeleteRejection("not applied")
        telegram.delete_behavior = reject
        claimed = await jobs.claim()
        assert claimed is not None
        with pytest.raises(JobError) as failure:
            await adapter.handle(claimed)
        await jobs._fail_claimed(claimed, failure.value.code, str(failure.value), retryable=True)
        telegram.can_delete = False
        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.UNCERTAIN
        assert telegram.deletes == [("chat-1", 7)]
    finally:
        await jobs.close()
        await storage.close()
