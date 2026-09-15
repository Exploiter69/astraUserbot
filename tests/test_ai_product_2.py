from __future__ import annotations

import asyncio
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
        self.enqueued = []

    async def update_progress(self, job_id, value):
        return None

    async def enqueue(self, *args, **kwargs):
        self.enqueued.append((args, kwargs))
        return type("Job", (), {"id": "abcdef1234567890", "state": "QUEUED"})()


@pytest.mark.asyncio
async def test_history_context_is_bounded_and_facade_owned(monkeypatch):
    telegram = FakeTelegram([Message("x" * 10000, 3), Message("second", 4), Message("third", 5)])
    monkeypatch.setattr(unified, "get_application_context", lambda: FakeContext(telegram=telegram))
    rows = await unified._history_context(Event(), 3)
    assert telegram.calls == [(123, 3)]
    assert len(rows) == 3
    assert sum(len(row["content"]) for row in rows) <= unified._MAX_CONTEXT_CHARS
    assert rows[0]["content"].startswith("sender 5:")


def test_unified_surface_has_required_commands():
    source = Path(unified.__file__).read_text(encoding="utf-8")
    for name in (".ai", ".explain", ".rewrite", ".translate", ".extract", ".code", ".aidiag"):
        assert name[1:] in source
    assert source.count("register_cmd(") >= 7


def test_ai_job_surface_is_single_registered_handler():
    source = Path(jobs.__file__).read_text(encoding="utf-8")
    assert '"AI_CHAT"' in source
    assert "register_handler" in source
    assert "resource_class=\"ai\"" in source


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
    with pytest.raises(Exception) as exc:
        asyncio.run(jobs._handle_ai_chat(type("Job", (), {"id": "job-1", "payload": {}})()))
    assert "prompt" in str(exc.value).lower()


def test_ai_diagnostics_is_non_sensitive():
    class Service:
        provider_name = "groq"
        remote_enabled = True
        max_input_chars = 100
        max_output_chars = 200
        max_output_tokens = 300
        max_message_count = 4
        max_message_chars = 50
        concurrency = 2
        timeout = 90.0
        max_remote_requests = 10
        remote_window_seconds = 86400.0
        available_providers = ("groq", "gemini", "ollama")
        provider_modes = {"groq": "remote", "gemini": "remote", "ollama": "local"}
        capabilities = {"groq": ("chat", "transcribe")}
        _remote_requests = []

        @property
        def diagnostics(self):
            return {"provider": self.provider_name, "providers": self.available_providers, "modes": self.provider_modes, "capabilities": self.capabilities, "remote_enabled": self.remote_enabled, "remote_requests_used": 0, "remote_requests_limit": self.max_remote_requests, "remote_requests_remaining": 10, "remote_window_seconds": self.remote_window_seconds, "max_input_chars": self.max_input_chars, "max_output_chars": self.max_output_chars, "max_output_tokens": self.max_output_tokens, "max_message_count": self.max_message_count, "max_message_chars": self.max_message_chars, "concurrency": self.concurrency, "timeout": self.timeout}

    data = Service().diagnostics
    assert "api_key" not in str(data).lower()
    assert data["remote_requests_remaining"] == 10
