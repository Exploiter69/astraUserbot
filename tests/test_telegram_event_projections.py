import tempfile
import unittest

from core.services.storage import StorageService
from core.services.telegram_event_journal import TelegramEventJournal
from core.services.telegram_event_projections import TelegramEventProjections
from core.services.telegram_events import TelegramEvent


class TelegramEventProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(self.tmp.name)
        await self.storage.start()
        self.journal = TelegramEventJournal(self.storage)
        await self.journal.start()
        self.projections = TelegramEventProjections(self.storage, self.journal)
        await self.projections.start()

    async def asyncTearDown(self):
        await self.projections.close()
        await self.journal.close()
        await self.storage.close()
        self.tmp.cleanup()

    async def test_pending_event_is_projected_and_marked_processed(self):
        event = TelegramEvent("e1", "MESSAGE_NEW", 10.0, "chat:1", 42, 7, {"text": "hello"})
        self.assertTrue(await self.journal.append(event))
        self.assertEqual(await self.projections.process_pending(), 1)
        row = await self.journal.get("e1")
        self.assertEqual(row["processing_state"], "PROCESSED")
        timeline = await self.storage.fetchall("SELECT * FROM telegram_timeline WHERE event_id='e1'")
        self.assertEqual(len(timeline), 1)
        latest = await self.storage.fetchall("SELECT * FROM telegram_latest_messages WHERE message_id=42 AND source_peer='chat:1'")
        self.assertEqual(len(latest), 1)

    async def test_edit_replaces_latest_message_projection(self):
        await self.journal.append(TelegramEvent("e1", "MESSAGE_NEW", 10.0, "chat:1", 42, 7, {"text": "old"}))
        await self.journal.append(TelegramEvent("e2", "MESSAGE_EDIT", 20.0, "chat:1", 42, 7, {"text": "new"}))
        self.assertEqual(await self.projections.process_pending(), 2)
        rows = await self.storage.fetchall("SELECT event_id,payload_json FROM telegram_latest_messages WHERE message_id=42 AND source_peer='chat:1'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_id"], "e2")
        self.assertIn("new", rows[0]["payload_json"])

    async def test_rebuild_restores_derived_state(self):
        await self.journal.append(TelegramEvent("e1", "MESSAGE_NEW", 10.0, "chat:1", 42, 7, {"text": "hello"}))
        await self.journal.append(TelegramEvent("e2", "CHAT_MEMBER_CHANGED", 11.0, "chat:1", None, 8, {"action": "join"}))
        self.assertEqual(await self.projections.process_pending(), 2)
        await self.storage.execute("DELETE FROM telegram_timeline")
        await self.storage.execute("DELETE FROM telegram_entity_observations")
        await self.storage.execute("DELETE FROM telegram_latest_messages")
        self.assertEqual(await self.projections.rebuild(), 2)
        self.assertEqual(len(await self.storage.fetchall("SELECT * FROM telegram_timeline")), 2)
        self.assertEqual(len(await self.storage.fetchall("SELECT * FROM telegram_entity_observations")), 2)

    async def test_failed_event_is_retryable(self):
        event = TelegramEvent("e1", "MESSAGE_NEW", 10.0, "chat:1", 42, 7, {"text": "hello"})
        await self.journal.append(event)
        self.assertTrue(await self.journal.mark_processing("e1"))
        self.assertTrue(await self.journal.mark_failed("e1", "temporary"))
        self.assertEqual(await self.projections.process_pending(), 1)
        row = await self.journal.get("e1")
        self.assertEqual(row["processing_state"], "PROCESSED")
        self.assertEqual(row["attempt_count"], 2)
