from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from core.services.automation import AUTOMATION_JOB_TYPE, AutomationEngine, AutomationError
from core.services.jobs import JobEngine, JobError
from core.services.storage import StorageService


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[tuple[object, str, dict]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def send_message(self, entity, message, **kwargs):
        self.sent.append((entity, message, kwargs))
        self.started.set()
        if self.release.is_set():
            return {"message_id": len(self.sent)}
        await self.release.wait()
        return {"message_id": len(self.sent)}

    async def get_messages(self, _peer, limit=20):
        return []


class AutomationJobEngineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tmp.name))
        await self.storage.start()
        self.telegram = FakeTelegram()
        self.jobs = JobEngine(self.storage, worker_id="automation-integration", poll_seconds=0.05)
        self.engine = AutomationEngine(self.storage, self.jobs, self.telegram, owner_id=42)

    async def asyncTearDown(self) -> None:
        await self.engine.close()
        await self.jobs.close()
        await self.storage.close()
        self.tmp.cleanup()

    async def _rule(self, **overrides):
        spec = {
            "rule_id": "integration",
            "trigger": {"type": "MESSAGE_NEW"},
            "scope": {"chat_id": 123},
            "match": {"contains": "hello"},
            "actions": [{"type": "REPLY", "text": "world"}],
        }
        spec.update(overrides)
        return await self.engine.create_rule(**spec)

    async def test_real_jobengine_executes_and_persists_automation_run(self):
        await self.jobs.start()
        await self.engine.start()
        await self._rule()

        accepted = await self.engine.trigger(
            {
                "event_id": "integration-event",
                "event_type": "MESSAGE_NEW",
                "source_peer": "123",
                "entity_id": 7,
                "message_id": 9,
                "payload": {"text": "hello there"},
            }
        )
        self.assertEqual(accepted, 1)

        for _ in range(40):
            row = await self.storage.fetchone(
                "SELECT state FROM automation_runs WHERE trigger_event_id=?",
                ("integration-event",),
            )
            if row and row[0] == "COMPLETED":
                break
            await asyncio.sleep(0.05)
        else:
            self.fail("Automation run did not reach COMPLETED through JobEngine")

        self.assertEqual(len(self.telegram.sent), 1)
        action = await self.storage.fetchone(
            "SELECT state FROM automation_action_runs WHERE run_id=(SELECT run_id FROM automation_runs WHERE trigger_event_id=?)",
            ("integration-event",),
        )
        self.assertEqual(action[0], "COMPLETED")

    async def test_rule_version_fences_queued_job(self):
        await self.engine.start()
        first = await self._rule()
        accepted = await self.engine.trigger(
            {
                "event_id": "fence-event",
                "event_type": "MESSAGE_NEW",
                "source_peer": "123",
                "message_id": 9,
                "payload": {"text": "hello"},
            }
        )
        self.assertEqual(accepted, 1)
        job_row = await self.storage.fetchone(
            "SELECT id FROM jobs WHERE type=? ORDER BY created_at DESC LIMIT 1",
            (AUTOMATION_JOB_TYPE,),
        )
        self.assertIsNotNone(job_row)

        second = await self._rule(actions=[{"type": "REPLY", "text": "changed"}])
        self.assertEqual(second.version, first.version + 1)
        job = await self.jobs.get(str(job_row[0]))
        with self.assertRaises(JobError) as raised:
            await self.engine._handle_job(job)
        self.assertEqual(raised.exception.code, "AUTOMATION_RULE_VERSION_STALE")
        self.assertFalse(self.telegram.sent)

    async def test_worker_cancellation_marks_run_recovery_required(self):
        await self.jobs.start()
        await self.engine.start()
        await self._rule()

        accepted = await self.engine.trigger(
            {
                "event_id": "cancel-event",
                "event_type": "MESSAGE_NEW",
                "source_peer": "123",
                "message_id": 9,
                "payload": {"text": "hello"},
            }
        )
        self.assertEqual(accepted, 1)
        await asyncio.wait_for(self.telegram.started.wait(), timeout=2)

        await self.jobs.close()

        row = await self.storage.fetchone(
            "SELECT state,error_code FROM automation_runs WHERE trigger_event_id=?",
            ("cancel-event",),
        )
        self.assertEqual(row[0], "RECOVERY_REQUIRED")
        self.assertEqual(row[1], "WORKER_CANCELLED")

    async def test_invalid_action_handler_registration_is_rejected(self):
        await self.engine.start()
        with self.assertRaises(AutomationError):
            self.engine.register_action_handler("NOT_A_REAL_ACTION", lambda *_: None)
