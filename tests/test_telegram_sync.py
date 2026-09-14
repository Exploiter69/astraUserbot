from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.services.storage import StorageService
from core.services.telegram_sync import GAP_DETECTED, SYNCED, TelegramIncrementalSync


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail = False
        self.messages = [SimpleNamespace(id=101), SimpleNamespace(id=102), SimpleNamespace(id=103)]

    async def _call(self, method, peer, *, operation_class, priority, **kwargs):
        self.calls.append({"method": method, "peer": peer, "operation_class": operation_class, "priority": priority, **kwargs})
        if self.fail:
            raise RuntimeError("temporary failure")
        min_id = int(kwargs.get("min_id", 0))
        return [message for message in self.messages if message.id > min_id][: int(kwargs["limit"])]


class TelegramIncrementalSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tempdir.name))
        await self.storage.start()
        self.telegram = FakeTelegram()
        self.sync = TelegramIncrementalSync(self.telegram, self.storage, max_batch=2)

    async def asyncTearDown(self):
        await self.storage.close()
        self.tempdir.cleanup()

    async def test_initial_sync_is_bounded_and_persists_cursor(self):
        result = await self.sync.sync(123, limit=99)
        self.assertEqual(result.fetched, 2)
        self.assertEqual(result.last_message_id, 102)
        self.assertEqual(result.state, SYNCED)
        self.assertFalse(result.gap_detected)
        self.assertEqual(self.telegram.calls[-1]["limit"], 2)
        self.assertNotIn("min_id", self.telegram.calls[-1])

        cursor = await self.sync.cursor(123)
        self.assertEqual(cursor.last_message_id, 102)
        self.assertEqual(cursor.sync_state, SYNCED)

    async def test_next_sync_resumes_from_cursor(self):
        await self.sync.sync(123, limit=2)
        result = await self.sync.sync(123, limit=2)
        self.assertEqual(result.last_message_id, 103)
        self.assertEqual(self.telegram.calls[-1]["min_id"], 102)

    async def test_failed_sync_is_marked_and_next_run_records_gap(self):
        self.telegram.fail = True
        with self.assertRaises(RuntimeError):
            await self.sync.sync(123, limit=2)
        failed = await self.sync.cursor(123)
        self.assertEqual(failed.sync_state, "FAILED")

        self.telegram.fail = False
        result = await self.sync.sync(123, limit=2)
        self.assertTrue(result.gap_detected)
        self.assertEqual(result.state, GAP_DETECTED)
        cursor = await self.sync.cursor(123)
        self.assertTrue(cursor.gap_detected)

    async def test_restart_reuses_durable_cursor(self):
        await self.sync.sync(123, limit=2)
        restarted = TelegramIncrementalSync(self.telegram, self.storage, max_batch=2)
        cursor = await restarted.cursor(123)
        self.assertEqual(cursor.last_message_id, 102)
        result = await restarted.sync(123, limit=2)
        self.assertEqual(result.last_message_id, 103)
        self.assertEqual(self.telegram.calls[-1]["min_id"], 102)


if __name__ == "__main__":
    unittest.main()
