from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from core.services.jobs import JobError
from core.services.search import SearchService
from core.services.storage import StorageService
from core.services.telegram_archive import TelegramArchiveJobModel
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


async def seed_job(storage: StorageService, job_id: str, payload: dict) -> None:
    await storage.execute(
        "INSERT INTO jobs(id,type,state,payload_json,owner,parent_id,idempotency_key,resource_class,priority,created_at,updated_at,available_at,max_attempts,verify_required) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, TelegramArchiveJobModel.JOB_TYPE, "QUEUED", __import__("json").dumps(payload), None, None, None, "telegram_archive", 0, 0.0, 0.0, 0.0, 3, 0),
    )


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

    payload = {"peer": "123", "limit": 101, "min_message_id": 0, "include_media": False}
    await seed_job(storage, "archive-job", payload)
    job = type("Job", (), {"id": "archive-job", "payload": payload})()
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


@pytest.mark.asyncio
async def test_archive_worker_resume_uses_durable_archived_count(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    search = SearchService(storage, tmp_path)
    await search.start()
    jobs = FakeJobs()

    class ResumeTelegram:
        def __init__(self):
            self.calls = []
        async def get_messages(self, peer, *, limit, max_id=None):
            self.calls.append((peer, limit, max_id))
            return [FakeMessage(2, "message 2"), FakeMessage(1, "message 1")]

    telegram = ResumeTelegram()
    service = TelegramArchiveService(storage, telegram, search, FakeMedia(), jobs, tmp_path)
    await service.start()
    payload = {"peer": "123", "limit": 5, "min_message_id": 0, "include_media": False}
    await seed_job(storage, "resume-job", payload)
    await service._save_cursor("resume-job", 2, 3, 0, 0)

    job = type("Job", (), {"id": "resume-job", "payload": payload})()
    result = await service._handle_job(job)

    assert result["archived"] == 5
    assert telegram.calls == [("123", 2, 2)]
    await storage.conn.close()


@pytest.mark.asyncio
async def test_archive_worker_classifies_fetch_failures_as_retryable(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    search = SearchService(storage, tmp_path)
    await search.start()
    jobs = FakeJobs()

    class FailingTelegram:
        async def get_messages(self, *_args, **_kwargs):
            raise RuntimeError("temporary transport failure")

    service = TelegramArchiveService(storage, FailingTelegram(), search, FakeMedia(), jobs, tmp_path)
    await service.start()
    payload = {"peer": "123", "limit": 1, "min_message_id": 0, "include_media": False}
    await seed_job(storage, "failure-job", payload)
    job = type("Job", (), {"id": "failure-job", "payload": payload})()

    with pytest.raises(JobError) as raised:
        await service._handle_job(job)
    assert raised.value.code == "ARCHIVE_FETCH_FAILED"
    assert raised.value.retryable is True
    await storage.conn.close()


@pytest.mark.asyncio
async def test_archive_media_is_content_addressed(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    search = SearchService(storage, tmp_path)
    await search.start()

    class Workspace:
        def __init__(self, path: Path):
            self.path = path

    class Media:
        max_input_bytes = 1024 * 1024
        def validate_telegram_media(self, _media):
            return None
        async def create_workspace(self, _name):
            path = tmp_path / "workspace"
            path.mkdir(exist_ok=True)
            return Workspace(path)
        async def download_telegram_media(self, _callback, _media, *, workspace):
            target = workspace.path / "photo.jpg"
            target.write_bytes(b"archive-bytes")
            return str(target)
        async def cleanup(self, _workspace):
            return None

    class Telegram:
        async def download_media(self, *_args, **_kwargs):
            raise AssertionError("fake media adapter should own the download")

    jobs = FakeJobs()
    service = TelegramArchiveService(storage, Telegram(), search, Media(), jobs, tmp_path)
    await service.start()
    message = FakeMessage(1, "with media", media=object())
    request = type("Request", (), {"peer": "123", "include_media": True})()
    metadata = await service._archive_message(request, message, job_id="media-job", media_bytes_used=0, media_count=0)

    assert metadata["media_status"] == "ARCHIVED"
    assert len(metadata["media_sha256"]) == 64
    stored = tmp_path / metadata["media_path"]
    assert stored.is_file()
    assert stored.read_bytes() == b"archive-bytes"
    await storage.conn.close()
