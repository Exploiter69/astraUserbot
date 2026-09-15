from __future__ import annotations

from pathlib import Path

import pytest

from core.services.jobs import JobEngine, JobState
from core.services.search import SearchService
from core.services.storage import StorageService
from core.services.telegram_archive_engine import TelegramArchiveService


class FakeTelegram:
    async def get_messages(self, *_args, **_kwargs):
        return []


class FakeMedia:
    max_input_bytes = 1024 * 1024


@pytest.mark.asyncio
async def test_archive_enqueue_reuses_active_job_but_not_terminal_job(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    search = SearchService(storage, tmp_path)
    await search.start()
    jobs = JobEngine(storage)
    service = TelegramArchiveService(storage, FakeTelegram(), search, FakeMedia(), jobs, tmp_path)
    await service.start()

    first = await service.enqueue("123", limit=5, owner="owner")
    duplicate = await service.enqueue("123", limit=5, owner="owner")
    assert duplicate.id == first.id

    claimed = await jobs.claim(("TELEGRAM_ARCHIVE",))
    assert claimed is not None
    assert claimed.id == first.id
    await jobs.fail(first.id, "TEST_FAILURE", "terminal test failure", retryable=False)
    failed = await jobs.get(first.id)
    assert failed.state is JobState.FAILED

    retry = await service.enqueue("123", limit=5, owner="owner")
    assert retry.id != first.id
    assert (await jobs.get(first.id)).state is JobState.FAILED
    assert (await jobs.get(retry.id)).state is JobState.QUEUED

    await jobs.close()
    await storage.conn.close()
