from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from core.services.storage import StorageService
from core.services.telegram_event_journal import TelegramEventJournal
from core.services.telegram_events import TelegramEvent


class TelegramEventJournalTests(unittest.TestCase):
    def _event(self, *, event_id: str = "evt-1", text: str = "hello") -> TelegramEvent:
        return TelegramEvent(
            event_id=event_id,
            event_type="MESSAGE_NEW",
            observed_at=100.0,
            source_peer="42",
            message_id=7,
            entity_id=99,
            payload={"text": text},
        )

    def test_persists_and_reloads_event_with_processing_state(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as root:
                storage = StorageService(Path(root))
                await storage.start()
                journal = TelegramEventJournal(storage)
                await journal.start()
                self.assertTrue(await journal.append(self._event()))
                row = await journal.get("evt-1")
                self.assertEqual(row["processing_state"], "PENDING")
                self.assertEqual(row["event_type"], "MESSAGE_NEW")
                self.assertEqual(await journal.mark_processing("evt-1"), True)
                self.assertEqual(await journal.mark_processed("evt-1"), True)
                row = await journal.get("evt-1")
                self.assertEqual(row["processing_state"], "PROCESSED")
                await journal.close()
                await storage.close()

                storage2 = StorageService(Path(root))
                await storage2.start()
                journal2 = TelegramEventJournal(storage2)
                await journal2.start()
                row = await journal2.get("evt-1")
                self.assertEqual(row["processing_state"], "PROCESSED")
                await journal2.close()
                await storage2.close()

        asyncio.run(scenario())

    def test_fingerprint_is_idempotency_boundary(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as root:
                storage = StorageService(Path(root))
                await storage.start()
                journal = TelegramEventJournal(storage)
                await journal.start()
                self.assertTrue(await journal.append(self._event(event_id="evt-1")))
                self.assertFalse(await journal.append(self._event(event_id="evt-2")))
                rows = await journal.list_pending(limit=10)
                self.assertEqual(len(rows), 1)
                await journal.close()
                await storage.close()

        asyncio.run(scenario())

    def test_failure_state_is_bounded_and_retryable(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as root:
                storage = StorageService(Path(root))
                await storage.start()
                journal = TelegramEventJournal(storage)
                await journal.start()
                await journal.append(self._event())
                self.assertTrue(await journal.mark_processing("evt-1"))
                self.assertTrue(await journal.mark_failed("evt-1", "x" * 5000))
                row = await journal.get("evt-1")
                self.assertEqual(row["processing_state"], "FAILED")
                self.assertLessEqual(len(row["last_error"]), 1024)
                self.assertTrue(await journal.mark_processing("evt-1"))
                await journal.close()
                await storage.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
