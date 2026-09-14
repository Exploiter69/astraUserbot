from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from core.services.search import SearchService
from core.services.storage import StorageService
from core.services.telegram_archive_engine import TelegramArchiveService


@dataclass
class FakeMessage:
    id: int
    message: str
    sender_id: int = 7
    reply_to_msg_id: int | None = None
    date: object | None = None
    edit_date: object | None = None
    media: object | None = None


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int | None]] = []

    async def get_messages(self, peer: str, *, limit: int, max_id: int | None = None):
        self.calls.append((peer, limit, max_id))
        if max_id is None:
            return [FakeMessage(i, f"message {i}") for i in range(101, 1, -1)]
        if max_id == 1:
            return [FakeMessage(1, "message 1")]
        return []


class FakeMedia:
    max_input_bytes = 512 * 1024 * 1024

    def validate_telegram_media(self, media):
        raise AssertionError("media should not be touched in metadata-only tests")


class FakeJobs:
    def __init__(self) -> None:
        self.handlers = {}
        self.progress: list[float] = []

    def register_handler(self, job_type, handler):
        self.handlers[job_type] = handler

    async def update_progress(self, _job_id, progress):
        self.progress.append(progress)


@pytest.mark.asyncio
async def test_archive_worker_is_bounded_resumable_and_searchable(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    search = SearchService(storage, tmp_path)
    await search.start()
    telegram = FakeTelegram()
    jobs = FakeJobs()
    service = TelegramArchiveService(storage, telegram, search, FakeMedia(), jobs, tmp_path)
    await service.start()

    job = type("Job", (), {"id": "archive-job", "payload": {"peer": "123", "limit": 101, "min_message_id": 0, "include_media": False}})()
    result = await service._handle_job(job)

    assert result["archived"] == 101
    assert len(telegram.calls) == 2
    assert telegram.calls[0] == ("123", 100, None)
    assert telegram.calls[1] == ("123", 1, 1)
    row = await storage.fetchone("SELECT COUNT(*) FROM search_documents WHERE source='archive_message'")
    assert row is not None
    assert int(row[0]) == 101

    results = await service.search_archive("message 4", limit=10)
    assert len(results) == 1
    assert results[0]["ref"] == "123:4"

    cursor = await storage.fetchone("SELECT payload_json FROM job_events WHERE job_id='archive-job' AND event_type='ARCHIVE_CURSOR' ORDER BY id DESC LIMIT 1")
    assert cursor is not None
    assert '"completed":true' in str(cursor[0])
    assert jobs.progress[-1] == 1.0

    await storage.conn.close()
