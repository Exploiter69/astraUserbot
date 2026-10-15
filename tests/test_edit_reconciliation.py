from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.services.edit_jobs import (
    AuthoritativeEditRejection, EDIT_EFFECT_CLASS, EDIT_JOB_TYPE, EditJobAdapter,
)
from core.services.jobs import JobEngine, JobError, JobState
from core.services.storage import StorageService


@dataclass
class FakeMessage:
    id: int
    message: str
    sender_id: int = 42
    date: datetime = datetime.now(timezone.utc)


class FakeTelegram:
    def __init__(self):
        self.client = self
        self.messages = {7: FakeMessage(7, "before")}
        self.edits = []
        self.edit_behavior = None
        self.history_error = None

    async def get_me(self):
        return SimpleNamespace(id=42)

    async def get_messages(self, target, *, limit=100, min_id=None, max_id=None):
        if self.history_error:
            raise self.history_error
        return [
            message for mid, message in self.messages.items()
            if (min_id is None or mid > min_id) and (max_id is None or mid < max_id)
        ][:limit]

    async def edit_message(self, target, message_id, text):
        self.edits.append((target, message_id, text))
        if self.edit_behavior is not None:
            return await self.edit_behavior(target, message_id, text)
        self.messages[message_id].message = text
        return self.messages[message_id]


async def make_services(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    jobs = JobEngine(storage, worker_id="edit-reconcile-test", poll_seconds=0.01)
    telegram = FakeTelegram()
    adapter = EditJobAdapter(jobs, telegram, storage)
    return storage, jobs, telegram, adapter


async def mark_uncertain(storage, job_id):
    await storage.execute(
        "UPDATE jobs SET state=?, attempt_count=1, started_at=? WHERE id=?",
        (JobState.UNCERTAIN.value, time.time() - 1, job_id),
    )


@pytest.mark.asyncio
async def test_edit_happened_completes_without_reapplying(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(EDIT_JOB_TYPE, {"target": "chat-1", "message_id": 7, "text": "after"})
        await adapter.handle(job)
        await mark_uncertain(storage, job.id)
        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.COMPLETED
        assert telegram.edits == [("chat-1", 7, "after")]
        assert telegram.messages[7].message == "after"
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_edit_not_happened_authoritative_rejection_allows_one_retry(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(EDIT_JOB_TYPE, {"target": "chat-1", "message_id": 7, "text": "after"})
        async def reject_once(target, message_id, text):
            telegram.edit_behavior = None
            raise AuthoritativeEditRejection("fake explicit rejection")
        telegram.edit_behavior = reject_once
        claimed = await jobs.claim()
        assert claimed is not None
        with pytest.raises(JobError) as failure:
            await adapter.handle(claimed)
        assert failure.value.code == "EDIT_REJECTED"
        assert await jobs._fail_claimed(claimed, failure.value.code, str(failure.value), retryable=True)
        assert (await jobs.get(job.id)).state == JobState.UNCERTAIN

        assert (await jobs.requeue_uncertain(job.id)).state == JobState.QUEUED
        second = await jobs.claim()
        assert second is not None and second.id == job.id
        result = await adapter.handle(second)
        assert await jobs._complete_claimed(second, result)
        assert (await jobs.get(job.id)).state == JobState.COMPLETED
        assert len(telegram.edits) == 2
        assert telegram.messages[7].message == "after"
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["target_inaccessible", "deleted", "later_edit", "timeout"])
async def test_edit_unknown_stays_uncertain_without_replay(tmp_path, case):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(EDIT_JOB_TYPE, {"target": "chat-1", "message_id": 7, "text": "after"})
        if case == "target_inaccessible":
            telegram.history_error = RuntimeError("peer inaccessible")
        elif case == "deleted":
            telegram.messages.clear()
        elif case == "later_edit":
            # No authoritative rejection; a differing value could be a later edit.
            pass
        elif case == "timeout":
            jobs.RECONCILER_TIMEOUT_SECONDS = 0.02
            original = telegram.get_messages
            async def slow_get(*args, **kwargs):
                import asyncio
                await asyncio.sleep(1)
                return await original(*args, **kwargs)
            telegram.get_messages = slow_get

        # Persist an attempt and force UNCERTAIN. For later_edit, mutate after the
        # attempt so the current state is neither intended nor safe baseline.
        claimed = await jobs.claim()
        assert claimed is not None
        await adapter._record_attempt(claimed, "chat-1", 7, "after", "before", time.time() - 1)
        await mark_uncertain(storage, job.id)
        if case == "later_edit":
            telegram.messages[7].message = "changed by another actor"
        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.UNCERTAIN
        assert len(telegram.edits) == 0
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_edit_happened_does_not_complete_other_unknown_required_effect(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(EDIT_JOB_TYPE, {"target": "chat-1", "message_id": 7, "text": "after"})
        claimed = await jobs.claim()
        assert claimed is not None
        await adapter._record_attempt(claimed, "chat-1", 7, "after", "before", time.time() - 1)
        telegram.messages[7].message = "after"
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
        assert telegram.edits == []
    finally:
        await jobs.close()
        await storage.close()
