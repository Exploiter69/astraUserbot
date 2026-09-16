from __future__ import annotations

from pathlib import Path

import pytest

from plugins.ai_gateway import jobs, unified


class FakeTelegram:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    async def get_messages(self, chat_id, *, limit):
        self.calls.append((chat_id, limit))
        return self.messages[:limit]


class FakeContext:
    def __init__(self, **services):
        self.services = services

    def get(self, name):
        return self.services[name]


class Message:
    def __init__(self, text, sender_id=1):
        self.text = text
        self.sender_id = sender_id


class Event:
    chat_id = 123
    is_reply = False


class FakeJobs:
    def __init__(self):
        self.handlers = {}

    async def update_progress(self, job_id, value):
        return None


@pytest.mark.asyncio
async def test_history_context_is_bounded_and_facade_owned(monkeypatch):
    telegram = FakeTelegram([Message("x" * 10000, 3), Message("second", 4), Message("third", 5)])
    monkeypatch.setattr(unified, "get_application_context", lambda: FakeContext(telegram=telegram))
    rows = await unified._history_context(Event(), 3)
    assert telegram.calls == [(123, 3)]
    assert len(rows) == 3
    assert sum(len(row["content"]) for row in rows) <= unified._MAX_CONTEXT_CHARS
    assert rows[0]["content"].startswith("sender 5:")


def test_telegram_media_kind_handles_telethon_photo_without_mime():
    class PhotoMedia:
        photo = object()
        mime_type = None

    class AudioDocument:
        document = type("Document", (), {"mime_type": "audio/ogg"})()
        mime_type = None

    assert unified._media_kind(PhotoMedia()) == "image"
    assert unified._media_kind(AudioDocument()) == "audio"


def test_telegram_media_kind_prefers_explicit_mime():
    class ImageDocument:
        document = type("Document", (), {"mime_type": "image/jpeg"})()
        mime_type = None

    class AudioMedia:
        mime_type = "audio/mpeg"

    assert unified._media_kind(ImageDocument()) == "image"
    assert unified._media_kind(AudioMedia()) == "audio"


def test_unified_surface_has_required_commands():
    source = Path(unified.__file__).read_text(encoding="utf-8")
    for name in (".ai", ".explain", ".rewrite", ".translate", ".extract", ".code", ".aidiag"):
        assert name[1:] in source
    assert source.count("register_cmd(") >= 7


def test_ai_job_surface_is_single_registered_handler():
    source = Path(jobs.__file__).read_text(encoding="utf-8")
    assert '"AI_CHAT"' in source
    assert "register_handler" in source
    assert 'resource_class="ai"' in source


@pytest.mark.asyncio
async def test_ai_job_handler_returns_provider_neutral_result(monkeypatch):
    class AI:
        async def chat(self, messages):
            return type("Response", (), {"text": "answer", "provider": "fake", "model": "fake-model", "input_chars": 6, "output_chars": 6})()

    context = FakeContext(ai=AI(), jobs=FakeJobs())
    monkeypatch.setattr(jobs, "get_application_context", lambda: context)
    job = type("Job", (), {"id": "job-1", "payload": {"prompt": "hello"}})()
    result = await jobs._handle_ai_chat(job)
    assert result == {"text": "answer", "provider": "fake", "model": "fake-model", "input_chars": 6, "output_chars": 6}


def test_ai_job_invalid_payload_is_non_retryable():
    with pytest.raises(jobs.JobError) as exc:
        jobs._job_prompt("")
    assert exc.value.code == "AI_INVALID_PAYLOAD"
    assert not exc.value.retryable


def test_ai_diagnostics_contract_is_non_sensitive():
    source = Path(__import__("core.services.ai", fromlist=["AIService"]).__file__).read_text(encoding="utf-8")
    assert "def diagnostics" in source
    assert "remote_requests_remaining" in source
    block = source[source.find("def diagnostics"):source.find("def diagnostics") + 2500]
    assert "api_key" not in block.lower()
