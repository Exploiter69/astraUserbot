from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.services.jobs import JobEngine, JobError, JobState
from core.services.storage import StorageService
from core.services.upload_jobs import (
    AuthoritativeUploadRejection, UPLOAD_EFFECT_CLASS, UPLOAD_JOB_TYPE,
    UploadJobAdapter,
)


@dataclass
class FakeFile:
    name: str = "clip.mp4"
    size: int = 1234
    mime_type: str = "video/mp4"


@dataclass
class FakeMessage:
    id: int
    sender_id: int = 42
    message: str = "caption"
    date: datetime | None = None
    media: object | None = None
    file: object | None = None

    def __post_init__(self):
        if self.date is None:
            self.date = datetime.now(timezone.utc)
        if self.media is None:
            self.media = SimpleNamespace(document=object())
        if self.file is None:
            self.file = FakeFile()


class FakeTelegram:
    def __init__(self):
        self.client = self
        self.history = []
        self.sent = []
        self.send_behavior = None
        self.history_error = None
        self.history_incomplete = False
        self.next_id = 101

    async def get_me(self):
        return SimpleNamespace(id=42)

    async def send_file(self, target, file, *, caption=None):
        self.sent.append((target, file, caption))
        if self.send_behavior is not None:
            return await self.send_behavior(target, file, caption)
        message = FakeMessage(self.next_id, message=caption or "")
        self.next_id += 1
        self.history.insert(0, message)
        return message

    async def get_messages(self, target, *, limit=100):
        if self.history_error:
            raise self.history_error
        if self.history_incomplete:
            return None
        return list(self.history[:limit])


async def make_services(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    jobs = JobEngine(storage, worker_id="upload-reconcile-test", poll_seconds=0.01)
    telegram = FakeTelegram()
    adapter = UploadJobAdapter(jobs, telegram, storage)
    return storage, jobs, telegram, adapter


async def mark_uncertain(storage, job_id):
    await storage.execute(
        "UPDATE jobs SET state=?, attempt_count=1, started_at=? WHERE id=?",
        (JobState.UNCERTAIN.value, time.time() - 1, job_id),
    )


def payload(**overrides):
    result = {
        "target": "chat-1",
        "file": "/tmp/clip.mp4",
        "caption": "caption",
        "media_metadata": {
            "file_name": "clip.mp4", "size": 1234, "mime_type": "video/mp4",
        },
    }
    result.update(overrides)
    return result


@pytest.mark.asyncio
async def test_upload_happened_recorded_published_id_and_media_metadata_no_republish(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(UPLOAD_JOB_TYPE, payload())
        await adapter.handle(job)
        assert len(telegram.sent) == 1
        await mark_uncertain(storage, job.id)

        result = await jobs.requeue_uncertain(job.id)

        assert result.state == JobState.COMPLETED
        assert len(telegram.sent) == 1
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_upload_not_happened_authoritative_rejection_allows_one_retry(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(UPLOAD_JOB_TYPE, payload())

        async def reject_once(_target, _file, _caption):
            telegram.send_behavior = None
            raise AuthoritativeUploadRejection("publication not accepted")

        telegram.send_behavior = reject_once
        first = await jobs.claim()
        assert first is not None
        with pytest.raises(JobError) as failure:
            await adapter.handle(first)
        assert failure.value.code == "UPLOAD_REJECTED"
        assert await jobs._fail_claimed(
            first, failure.value.code, str(failure.value), retryable=True
        )
        assert (await jobs.get(job.id)).state == JobState.UNCERTAIN

        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.QUEUED
        second = await jobs.claim()
        assert second is not None and second.id == job.id
        value = await adapter.handle(second)
        assert await jobs._complete_claimed(second, value)
        assert (await jobs.get(job.id)).state == JobState.COMPLETED
        assert len(telegram.sent) == 2
        assert len(telegram.history) == 1
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "history_incomplete", "ambiguous", "destination_inaccessible", "timeout",
])
async def test_upload_unknown_stays_uncertain_without_replay(tmp_path, case):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(UPLOAD_JOB_TYPE, payload())
        claimed = await jobs.claim()
        assert claimed is not None
        await adapter._record_attempt(
            claimed, "chat-1", "caption",
            {"file_name": "clip.mp4", "size": 1234, "mime_type": "video/mp4"},
            time.time() - 1,
        )
        await mark_uncertain(storage, job.id)
        if case == "history_incomplete":
            telegram.history_incomplete = True
        elif case == "ambiguous":
            telegram.history = [
                FakeMessage(201), FakeMessage(202),
            ]
        elif case == "destination_inaccessible":
            telegram.history_error = PermissionError("destination inaccessible")
        elif case == "timeout":
            jobs.RECONCILER_TIMEOUT_SECONDS = 0.02
            original = telegram.get_messages
            async def slow_history(*args, **kwargs):
                await asyncio.sleep(1)
                return await original(*args, **kwargs)
            telegram.get_messages = slow_history

        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.UNCERTAIN
        assert telegram.sent == []
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_upload_temporary_upload_handle_without_published_message_is_unknown(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(
            UPLOAD_JOB_TYPE,
            payload(temporary_upload_handle="temporary-chunk-token"),
        )
        claimed = await jobs.claim()
        assert claimed is not None
        await adapter._record_attempt(
            claimed, "chat-1", "caption",
            {"file_name": "clip.mp4", "size": 1234, "mime_type": "video/mp4"},
            time.time() - 1, "temporary-chunk-token",
        )
        # Deliberately no destination-visible publication in history.
        await mark_uncertain(storage, job.id)
        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.UNCERTAIN
        assert telegram.sent == []
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_upload_happened_does_not_complete_other_unknown_required_effect(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(UPLOAD_JOB_TYPE, payload())
        await adapter.handle(job)
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
        assert len(telegram.sent) == 1
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_upload_authoritative_rejection_without_clean_history_stays_unknown(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(UPLOAD_JOB_TYPE, payload())
        async def reject(_target, _file, _caption):
            raise AuthoritativeUploadRejection("not accepted")
        telegram.send_behavior = reject
        claimed = await jobs.claim()
        assert claimed is not None
        with pytest.raises(JobError) as failure:
            await adapter.handle(claimed)
        await jobs._fail_claimed(claimed, failure.value.code, str(failure.value), retryable=True)
        telegram.history_incomplete = True
        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.UNCERTAIN
        assert len(telegram.sent) == 1
    finally:
        await jobs.close()
        await storage.close()
