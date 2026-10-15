import asyncio
import json
import random
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
        await self.journal.append(
            TelegramEvent("e1", "MESSAGE_NEW", 10.0, "chat:1", 42, 7, {"text": "old"})
        )
        await self.journal.append(
            TelegramEvent("e2", "MESSAGE_EDIT", 20.0, "chat:1", 42, 7, {"text": "new"})
        )
        run_id = await self.replay.begin()
        result = await self.replay.replay(run_id, batch_size=1)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["processed_count"], 2)
        latest = await self.storage.fetchall(
            "SELECT event_id,payload_json FROM telegram_latest_messages WHERE message_id=42"
        )
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["event_id"], "e2")
        self.assertIn("new", latest[0]["payload_json"])

    async def test_cancel_is_safe_and_resume_uses_durable_cursor(self):
        for index in range(3):
            await self.journal.append(
                TelegramEvent(
                    f"e{index}",
                    "MESSAGE_NEW",
                    float(index),
                    "chat:1",
                    index,
                    7,
                    {"text": str(index)},
                )
            )
        run_id = await self.replay.begin()
        await self.replay.cancel()
        paused = await self.replay.replay(run_id, batch_size=1)
        self.assertEqual(paused["state"], "PAUSED")
        self.assertEqual(paused["processed_count"], 0)
        resumed = await self.replay.resume(run_id, batch_size=1)
        self.assertEqual(resumed["state"], "COMPLETED")
        self.assertEqual(resumed["processed_count"], 3)

    async def test_replay_state_survives_service_restart(self):
        await self.journal.append(
            TelegramEvent("e1", "MESSAGE_NEW", 10.0, "chat:1", 42, 7, {"text": "hello"})
        )
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
            await self.journal.append(
                TelegramEvent(
                    f"e{index}",
                    "MESSAGE_NEW",
                    float(index),
                    "chat:1",
                    index,
                    7,
                    {"text": str(index)},
                )
            )
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

    @staticmethod
    def _canonical_projection_snapshot(rows):
        return json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    async def _projection_snapshot(self):
        timeline = await self.storage.fetchall(
            "SELECT event_id,event_type,source_peer,entity_id,message_id,observed_at,payload_json "
            "FROM telegram_timeline ORDER BY event_id"
        )
        latest = await self.storage.fetchall(
            "SELECT message_id,source_peer,event_id,event_type,entity_id,payload_json,observed_at "
            "FROM telegram_latest_messages ORDER BY source_peer,message_id"
        )
        observations = await self.storage.fetchall(
            "SELECT event_id,entity_id,source_peer,event_type,observed_at,payload_json "
            "FROM telegram_entity_observations ORDER BY event_id"
        )
        return self._canonical_projection_snapshot({
            "timeline": [tuple(row) for row in timeline],
            "latest": [tuple(row) for row in latest],
            "observations": [tuple(row) for row in observations],
        })

    async def test_seeded_random_event_sequences_match_independent_journal_replay(self):
        # Fixed seeds make every generated sequence reproducible on CI and locally.
        for seed in (7, 41, 2026, 65537, 99173):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                for index in range(30):
                    event_type = rng.choice(("MESSAGE_NEW", "MESSAGE_EDIT"))
                    message_id = rng.randint(1, 12)
                    source_peer = f"chat:{rng.randint(1, 3)}"
                    entity_id = rng.randint(100, 105)
                    payload = {
                        "text": f"seed={seed};index={index};value={rng.getrandbits(24)}",
                        "sequence": index,
                    }
                    await self.journal.append(
                        TelegramEvent(
                            f"random-{seed}-{index}",
                            event_type,
                            float(seed * 100 + index),
                            source_peer,
                            message_id,
                            entity_id,
                            payload,
                        )
                    )

                # Materialize through the normal pending-event projection path.
                await self.projections.process_pending(limit=500)
                incremental = await self._projection_snapshot()

                # Clear and rebuild exclusively by replaying the durable journal.
                run_id = await self.replay.begin()
                result = await self.replay.replay(run_id, batch_size=17)
                self.assertEqual(result["state"], "COMPLETED")
                rebuilt = await self._projection_snapshot()
                self.assertEqual(incremental.encode("utf-8"), rebuilt.encode("utf-8"))

    async def test_projection_harness_detects_journal_divergence(self):
        await self.journal.append(
            TelegramEvent(
                "divergence-event",
                "MESSAGE_NEW",
                123.0,
                "chat:divergence",
                9001,
                77,
                {"text": "original payload"},
            )
        )
        await self.projections.process_pending(limit=10)
        before_tamper = await self._projection_snapshot()

        # Deliberately corrupt only the persisted source row in this temporary DB.
        await self.storage.execute(
            "UPDATE telegram_event_journal SET payload_json=? WHERE event_id=?",
            ('{"text":"tampered payload"}', "divergence-event"),
        )
        await self.projections.rebuild()
        after_rebuild = await self._projection_snapshot()
        self.assertNotEqual(
            before_tamper.encode("utf-8"),
            after_rebuild.encode("utf-8"),
            "projection comparison harness failed to detect a changed journal payload",
        )
