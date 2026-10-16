"""Contract tests for the Phase 5b fake Telegram dispatch primitives."""

from __future__ import annotations

import asyncio
import re

import pytest

from astra.testing.telegram import FakeTelegramClient, FakeTelegramEvent, emit_command
from core.registry import list_registrations, register_cmd


def test_fake_client_registers_and_removes_real_registry_wrapper() -> None:
    client = FakeTelegramClient()
    async def handler(event):
        return None

    registration = register_cmd(
        client, r"^\.step2-register$", handler, category="test"
    )
    try:
        assert (registration.wrapper, registration.event_builder) in client.handlers
        assert registration in list_registrations()
    finally:
        registration.unregister(client)
    assert (registration.wrapper, registration.event_builder) not in client.handlers
    assert registration not in list_registrations()


def test_emit_command_matching_calls_registered_wrapper_and_records_effects() -> None:
    client = FakeTelegramClient()
    observed = []

    async def handler(event):
        observed.append(event)
        await event.edit("edited")
        await event.reply("replied")
        await event.delete()

    registration = register_cmd(
        client, r"^\.step2-hello(?:\s+(.*))?$", handler, category="test"
    )
    try:
        result = asyncio.run(emit_command(client, ".step2-hello world"))
        assert result.matched is True
        assert result.handler is registration.wrapper
        assert len(observed) == 1
        assert observed[0].pattern_match.group(1) == "world"
        assert [effect.operation for effect in result.effects] == [
            "event.edit", "event.reply", "event.delete"
        ]
        assert [effect.order for effect in result.effects] == [1, 2, 3]
        assert [effect.result for effect in result.effects] == [
            None, None, None
        ]
        assert result.effects[0].args == ("edited",)
        assert result.effects[1].args == ("replied",)
    finally:
        registration.unregister(client)


def test_emit_command_nonmatching_does_not_invoke_handler() -> None:
    client = FakeTelegramClient()
    calls = []

    async def handler(event):
        calls.append(event)

    registration = register_cmd(
        client, r"^\.step2-hello$", handler, category="test"
    )
    try:
        result = asyncio.run(emit_command(client, ".step2-nope"))
        assert result.matched is False
        assert calls == []
        assert result.effects == ()
    finally:
        registration.unregister(client)


def test_out_false_returns_early_and_raw_wrapper_receives_original_event() -> None:
    client = FakeTelegramClient()
    received = []

    async def handler(event):
        received.append(event)

    registration = register_cmd(
        client, r"^\.step2-out$", handler, category="test"
    )
    try:
        result = asyncio.run(emit_command(client, ".step2-out", out=False))
        assert result.matched is True
        assert received == []
        assert result.effects == ()

        result = asyncio.run(emit_command(client, ".step2-out"))
        assert received == [result.event]
        assert type(result.event) is FakeTelegramEvent
        assert not type(result.event).__name__.endswith("CapabilityEventProxy")
    finally:
        registration.unregister(client)


def test_pattern_match_groups_and_metadata_are_populated() -> None:
    client = FakeTelegramClient()
    observed = []

    async def handler(event):
        observed.append((event.pattern_match.groups(), event.text, event.raw_text))

    registration = register_cmd(
        client, r"^\.step2-echo\s+(\w+)\s+(\d+)$", handler, category="test"
    )
    try:
        result = asyncio.run(emit_command(client, ".step2-echo alpha 42"))
        assert result.matched is True
        assert observed == [(("alpha", "42"), ".step2-echo alpha 42", ".step2-echo alpha 42")]
        assert result.event.chat_id is not None
        assert result.event.sender_id is not None
        assert result.event.id is not None
        assert result.event.client is client
    finally:
        registration.unregister(client)


def test_client_level_operations_are_recorded_in_order() -> None:
    client = FakeTelegramClient()
    async def run():
        await client.send_message("chat", "hello")
        await client.edit_message("chat", 12, "changed")
        await client.delete_messages("chat", [12])
    asyncio.run(run())
    assert [effect.operation for effect in client.effects] == [
        "client.send_message", "client.edit_message", "client.delete_messages"
    ]
    assert [effect.order for effect in client.effects] == [1, 2, 3]
    assert client.effects[0].args == ("chat", "hello")


def test_unsupported_event_method_fails_clearly() -> None:
    event = FakeTelegramEvent(".step2-unsupported")
    with pytest.raises(NotImplementedError, match="unsupported event method"):
        asyncio.run(event.forward_to("somewhere"))


def test_emit_dispatches_registered_wrapper_not_registration_handler() -> None:
    client = FakeTelegramClient()
    calls = []

    async def handler(event):
        calls.append("handler")

    registration = register_cmd(
        client, r"^\.step2-wrapper$", handler, category="test"
    )
    try:
        registration.handler = lambda event: calls.append("raw-handler")
        result = asyncio.run(emit_command(client, ".step2-wrapper"))
        assert result.matched is True
        assert calls == ["handler"]
    finally:
        registration.unregister(client)


def test_effect_record_captures_exceptions() -> None:
    event = FakeTelegramEvent(".step2-failure")

    async def broken_edit():
        async def fail():
            raise ValueError("synthetic edit failure")
        event._record("event.edit", ("x",), {}, fail)

    with pytest.raises(ValueError, match="synthetic edit failure"):
        asyncio.run(broken_edit())
    assert len(event.effects) == 1
    assert event.effects[0].exception == "ValueError: synthetic edit failure"


