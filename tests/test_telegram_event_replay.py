import asyncio
import tempfile
import unittest

from core.services.storage import StorageService
from core.services.telegram_event_journal import TelegramEventJournal
from core.services.telegram_event_projections import TelegramEventProjections
from core.services.telegram_event_replay import TelegramEventReplay
from core.services.telegram_events import TelegramEvent


class TelegramEventReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(self.tmp.name)
        await self.storage.start()
        self.journal = TelegramEventJournal(self.storage)
        await self.journal.start()
        self.projections = TelegramEventProjections(self.storage, self.journal)
        await self.projections.start()
        self.replay = TelegramEventReplay(self.storage, self.journal, self.projections)
        await self.replay.start()

    async def asyncTearDown(self):
        await self.replay.close()
        await self.projections.close()
        await self.journal.close()
        await self.storage.close()
        self.tmp.cleanup()

    async def test_replay_rebuilds_projection_and_tracks_progress(self):
        await self.journal.append(TelegramEvent("e1", "MESSAGE_NEW", 10.0, "chat:1", 42, 7, {"text": "old"}))
        await self.journal.append(TelegramEvent("e2", "MESSAGE_EDIT", 20.0, "chat:1", 42, 7, {"text": "new"}))
        run_id = await self.replay.begin()
        result = await self.replay.replay(run_id, batch_size=1)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["processed_count"], 2)
        latest = await self.storage.fetchall("SELECT event_id,payload_json FROM telegram_latest_messages WHERE message_id=42")
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["event_id"], "e2")
        self.assertIn("new", latest[0]["payload_json"])

    async def test_cancel_is_safe_and_resume_uses_durable_cursor(self):
        for index in range(3):
            await self.journal.append(TelegramEvent(f"e{index}", "MESSAGE_NEW", float(index), "chat:1", index, 7, {"text": str(index)}))
        run_id = await self.replay.begin()
        await self.replay.cancel()
        paused = await self.replay.replay(run_id, batch_size=1)
        self.assertEqual(paused["state"], "PAUSED")
        self.assertEqual(paused["processed_count"], 0)
        resumed = await self.replay.resume(run_id, batch_size=1)
        self.assertEqual(resumed["state"], "COMPLETED")
        self.assertEqual(resumed["processed_count"], 3)

    async def test_replay_state_survives_service_restart(self):
        await self.journal.append(TelegramEvent("e1", "MESSAGE_NEW", 10.0, "chat:1", 42, 7, {"text": "hello"}))
        run_id = await self.replay.begin()
        self.replay._cancelled = True
        paused = await self.replay.replay(run_id, batch_size=1)
        self.assertEqual(paused["state"], "PAUSED")
        await self.replay.close()
        replay2 = TelegramEventReplay(self.storage, self.journal, self.projections)
        await replay2.start()
        status = await replay2.status(run_id)
        self.assertEqual(status["state"], "PAUSED")
        completed = await replay2.resume(run_id, batch_size=1)
        self.assertEqual(completed["state"], "COMPLETED")
        await replay2.close()

    async def test_batch_size_is_bounded(self):
        run_id = await self.replay.begin()
        result = await self.replay.status(run_id)
        self.assertEqual(result["processed_count"], 0)
        with self.assertRaises(ValueError):
            await self.replay.begin(projection="unknown")

    async def test_replay_task_cancellation_marks_run_paused(self):
        for index in range(2):
            await self.journal.append(TelegramEvent(f"e{index}", "MESSAGE_NEW", float(index), "chat:1", index, 7, {"text": str(index)}))
        run_id = await self.replay.begin()
        original_apply = self.projections.apply_row

        async def slow_apply(row):
            await asyncio.sleep(0.05)
            await original_apply(row)

        self.projections.apply_row = slow_apply
        task = asyncio.create_task(self.replay.replay(run_id, batch_size=1))
        await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        status = await self.replay.status(run_id)
        self.assertEqual(status["state"], "PAUSED")
