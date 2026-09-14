from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from telethon import types

from core.services.telegram_events import TelegramEvent, TelegramEventCollector


class FakeClient:
    def __init__(self) -> None:
        self.handlers: list[tuple[object, object]] = []

    def add_event_handler(self, callback, builder) -> None:
        self.handlers.append((callback, builder))

    def remove_event_handler(self, callback, builder) -> None:
        self.handlers.remove((callback, builder))


class TelegramEventCollectorTests(unittest.TestCase):
    def test_start_registers_supported_event_families_and_close_unregisters(self) -> None:
        async def scenario() -> None:
            client = FakeClient()
            collector = TelegramEventCollector(client)
            await collector.start()
            self.assertEqual(len(client.handlers), 6)
            self.assertTrue(collector._started)
            await collector.close()
            self.assertEqual(client.handlers, [])
            self.assertFalse(collector._started)

        asyncio.run(scenario())

    def test_new_message_is_normalized_and_bounded(self) -> None:
        async def scenario() -> None:
            client = FakeClient()
            collector = TelegramEventCollector(client)
            received: list[TelegramEvent] = []
            collector.add_sink(received.append)
            message = SimpleNamespace(
                id=42,
                raw_text="x" * 5000,
                media=object(),
                out=True,
                reply_to=SimpleNamespace(reply_to_msg_id=7),
                sender_id=123,
            )
            event = SimpleNamespace(chat_id=99, sender_id=123, message=message)
            await collector._handle_new_message(event)
            self.assertEqual(len(received), 1)
            item = received[0]
            self.assertEqual(item.event_type, "MESSAGE_NEW")
            self.assertEqual(item.source_peer, "99")
            self.assertEqual(item.message_id, 42)
            self.assertEqual(item.entity_id, 123)
            self.assertEqual(len(item.payload["text"]), collector.MAX_TEXT_BYTES)
            self.assertTrue(item.payload["has_media"])
            self.assertTrue(item.payload["out"])
            self.assertEqual(item.payload["reply_to"], 7)
            self.assertEqual(item.schema_version, 1)

        asyncio.run(scenario())

    def test_delete_emits_bounded_events_and_sink_failure_isolated(self) -> None:
        async def scenario() -> None:
            collector = TelegramEventCollector(FakeClient())
            received: list[TelegramEvent] = []

            async def failing_sink(event: TelegramEvent) -> None:
                raise RuntimeError("sink failure")

            collector.add_sink(failing_sink)
            collector.add_sink(received.append)
            await collector._handle_message_delete(SimpleNamespace(chat_id=10, deleted_ids=list(range(150))))
            self.assertEqual(len(received), 100)
            self.assertEqual(received[0].message_id, 0)
            self.assertEqual(received[-1].message_id, 99)
            self.assertTrue(all(item.event_type == "MESSAGE_DELETE" for item in received))

        asyncio.run(scenario())

    def test_reaction_update_is_normalized_from_raw_telethon_update(self) -> None:
        async def scenario() -> None:
            collector = TelegramEventCollector(FakeClient())
            received: list[TelegramEvent] = []
            collector.add_sink(received.append)
            update = SimpleNamespace(peer=types.PeerUser(user_id=99), msg_id=42)
            await collector._handle_reaction(update)
            self.assertEqual(len(received), 1)
            item = received[0]
            self.assertEqual(item.event_type, "REACTION_CHANGED")
            self.assertEqual(item.message_id, 42)
            self.assertEqual(item.source_peer, "PeerUser(user_id=99)")
            self.assertEqual(item.payload["message"], 42)

        asyncio.run(scenario())

    def test_call_update_is_normalized_without_retaining_raw_update(self) -> None:
        async def scenario() -> None:
            collector = TelegramEventCollector(FakeClient())
            received: list[TelegramEvent] = []
            collector.add_sink(received.append)
            update = types.UpdatePhoneCall(phone_call=types.PhoneCallEmpty(id=55))
            await collector._handle_raw(update)
            self.assertEqual(len(received), 1)
            item = received[0]
            self.assertEqual(item.event_type, "CALL_STATE_CHANGED")
            self.assertEqual(item.payload["update"], "UpdatePhoneCall")
            self.assertEqual(item.payload["call_id"], 55)
            self.assertIsNone(item.source_peer)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
