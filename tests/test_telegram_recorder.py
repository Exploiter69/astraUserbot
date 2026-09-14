import asyncio
import tempfile
import unittest
from pathlib import Path

from core.services.storage import StorageService
from core.services.telegram import TelegramFacade
from core.services.telegram_recorder import TelegramOperationRecorder, request_fingerprint


class FakeTelegram:
    async def send_message(self, entity, message, **kwargs):
        await asyncio.sleep(0)
        return "sent"


class TelegramFlightRecorderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tempdir.name))
        await self.storage.start()

    async def asyncTearDown(self):
        await self.storage.close()
        self.tempdir.cleanup()

    async def test_migration_creates_telegram_operations_table(self):
        row = await self.storage.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='telegram_operations'"
        )
        self.assertIsNotNone(row)

    async def test_recorder_is_bounded_and_does_not_store_request_contents(self):
        recorder = TelegramOperationRecorder(self.storage, max_rows=2)
        for index in range(3):
            digest, size = request_fingerprint("send_message", ("chat:1", f"secret-{index}"), {})
            await recorder.record(
                operation_id=str(index),
                started_at=float(index),
                method="send_message",
                peer_id="chat:1",
                operation_class="WRITE",
                request_hash=digest,
                result_classification="SUCCESS",
                latency_ms=1.0,
                payload_size=size,
            )

        row = await self.storage.fetchone("SELECT COUNT(*) FROM telegram_operations")
        self.assertEqual(row[0], 2)
        rows = await self.storage.fetchall("SELECT request_hash FROM telegram_operations")
        self.assertTrue(all("secret-" not in row[0] for row in rows))

    async def test_facade_records_success_without_breaking_raw_operation(self):
        recorder = TelegramOperationRecorder(self.storage)
        facade = TelegramFacade(FakeTelegram(), retries=0, recorder=recorder)
        try:
            result = await facade.send_message("chat:9", "hello", parse_mode="html")
            self.assertEqual(result, "sent")
            row = await self.storage.fetchone(
                "SELECT method, peer_id, operation_class, result_classification, retry_count "
                "FROM telegram_operations ORDER BY id DESC LIMIT 1"
            )
            self.assertEqual(tuple(row), ("send_message", "chat:9", "WRITE", "SUCCESS", 0))
        finally:
            await facade.close()


if __name__ == "__main__":
    unittest.main()
