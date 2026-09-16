from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.services.automation import AUTOMATION_JOB_TYPE, AutomationEngine
from core.services.jobs import JobEngine
from core.services.storage import StorageService


class FakeTelegram:
    async def send_message(self, *_args, **_kwargs):
        return {"message_id": 1}

    async def get_messages(self, *_args, **_kwargs):
        return []


class AutomationDurabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tmp.name))
        await self.storage.start()
        self.jobs = JobEngine(self.storage, worker_id="automation-durability", poll_seconds=0.05)
        self.engine = AutomationEngine(self.storage, self.jobs, FakeTelegram(), owner_id=42)
        await self.engine.start()

    async def asyncTearDown(self) -> None:
        await self.engine.close()
        await self.jobs.close()
        await self.storage.close()
        self.tmp.cleanup()

    async def test_enqueue_pending_reconciles_to_existing_job_contract(self):
        rule = await self.engine.create_rule(
            rule_id="pending",
            trigger={"type": "MESSAGE_NEW"},
            scope={"chat_id": 123},
            match={"contains": "hello"},
            actions=[{"type": "REPLY", "text": "world"}],
        )
        event = {
            "event_id": "pending-event",
            "event_type": "MESSAGE_NEW",
            "source_peer": "123",
            "message_id": 9,
            "payload": {"text": "hello"},
        }
        run_id = "pending-run"
        idem = "automation:pending-idempotency"
        now = time.time()
        await self.storage.transaction([
            (
                "INSERT INTO automation_runs(run_id,rule_id,rule_version,trigger_event_id,trigger_type,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, rule.id, rule.version, "pending-event", "MESSAGE_NEW", "ENQUEUE_PENDING", now, now),
            ),
            (
                "INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)",
                (
                    "AUTOMATION_ENQUEUE_INTENT",
                    run_id,
                    self.engine._dump({
                        "rule_id": rule.id,
                        "rule_version": rule.version,
                        "trigger_type": "MESSAGE_NEW",
                        "event": event,
                        "idempotency_key": idem,
                    }),
                    now,
                ),
            ),
        ])

        await self.engine._reconcile_enqueue_pending()

        run = await self.storage.fetchone("SELECT state FROM automation_runs WHERE run_id=?", (run_id,))
        self.assertEqual(run[0], "QUEUED")
        job = await self.storage.fetchone("SELECT type,idempotency_key FROM jobs WHERE idempotency_key=?", (idem,))
        self.assertEqual(job[0], AUTOMATION_JOB_TYPE)

    async def test_schedule_guard_uses_durable_last_run(self):
        rule = await self.engine.create_rule(
            rule_id="scheduled",
            trigger={"type": "SCHEDULED", "at": time.time() - 1, "interval_seconds": 3600},
            scope={"chat_id": 123},
            match={},
            actions=[{"type": "TAG", "tag": "scheduled"}],
        )
        await self.engine.trigger(
            {
                "event_id": "schedule-first",
                "event_type": "SCHEDULED",
                "source_peer": "123",
                "payload": {"scheduled_at": rule.trigger["at"]},
            },
            trigger_type="SCHEDULED",
        )
        row = await self.storage.fetchone(
            "SELECT last_run_at FROM automation_cooldowns WHERE rule_id=? AND cooldown_key='schedule'",
            (rule.id,),
        )
        self.assertIsNotNone(row)
        self.assertGreater(float(row[0]), 0)
