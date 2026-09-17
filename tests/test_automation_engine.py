from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.services.automation import AutomationEngine, AutomationError, AUTOMATION_JOB_TYPE
from core.services.jobs import Job, JobError, JobState
from core.services.storage import StorageService


class FakeJobs:
    def __init__(self) -> None:
        self.handlers = {}
        self.enqueued = []

    def register_handler(self, job_type, handler):
        if job_type in self.handlers:
            raise ValueError(f"Job handler already registered: {job_type}")
        self.handlers[job_type] = handler

    async def enqueue(self, job_type, payload, **kwargs):
        self.enqueued.append((job_type, payload, kwargs))
        return SimpleNamespace(id=f"job-{len(self.enqueued)}")

    async def get(self, job_id):
        raise KeyError(job_id)

    async def list(self, **kwargs):
        return []


class FakeTelegram:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, entity, message, **kwargs):
        self.sent.append((entity, message, kwargs))
        return {"message_id": len(self.sent)}


class AutomationEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tmp.name))
        await self.storage.start()
        self.jobs = FakeJobs()
        self.telegram = FakeTelegram()
        self.engine = AutomationEngine(self.storage, self.jobs, self.telegram, owner_id=42)
        await self.engine.start()

    async def asyncTearDown(self) -> None:
        await self.engine.close()
        await self.storage.close()
        self.tmp.cleanup()

    async def _rule(self, **overrides):
        spec = {
            "rule_id": "hello",
            "trigger": {"type": "MESSAGE_NEW"},
            "scope": {"chat_id": 123},
            "match": {"contains": "hello"},
            "actions": [{"type": "REPLY", "text": "world"}],
        }
        spec.update(overrides)
        return await self.engine.create_rule(**spec)

    async def test_schema_is_created_and_versioned(self):
        tables = {row[0] for row in await self.storage.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"automation_schema", "automation_rules", "automation_runs", "automation_action_runs", "automation_cooldowns"} <= tables)
        version = await self.storage.fetchone("SELECT MAX(version) FROM automation_schema")
        self.assertEqual(version[0], 2)
        columns = {row[1] for row in await self.storage.fetchall("PRAGMA table_info(automation_rules)")}
        self.assertIn("deleted_at", columns)

    async def test_rule_is_declarative_owner_scoped_and_versioned(self):
        first = await self._rule()
        self.assertEqual(first.version, 1)
        self.assertEqual(first.owner, "42")
        second = await self._rule(actions=[{"type": "REPLY", "text": "changed"}])
        self.assertEqual(second.version, 2)
        self.assertEqual(second.actions[0]["text"], "changed")

    async def test_rejects_missing_explicit_scope(self):
        with self.assertRaises(AutomationError):
            await self._rule(scope={})

    async def test_rejects_telegram_rule_without_chat_scope(self):
        with self.assertRaises(AutomationError):
            await self._rule(scope={"entity_id": 7})

    async def test_event_scope_and_match_gate_enqueue(self):
        await self._rule()
        accepted = await self.engine.trigger({"event_id": "e1", "event_type": "MESSAGE_NEW", "source_peer": "123", "entity_id": 7, "message_id": 9, "payload": {"text": "hello there"}})
        self.assertEqual(accepted, 1)
        self.assertEqual(self.jobs.enqueued[0][0], AUTOMATION_JOB_TYPE)

    async def test_delete_tombstones_rule_and_preserves_completed_history(self):
        rule = await self._rule(rule_id="delete-me")
        accepted = await self.engine.trigger({"event_id": "delete-event", "event_type": "MESSAGE_NEW", "source_peer": "123", "entity_id": 7, "message_id": 9, "payload": {"text": "hello there"}})
        self.assertEqual(accepted, 1)
        run_id = self.jobs.enqueued[0][1]["run_id"]
        await self.storage.execute("UPDATE automation_runs SET state='COMPLETED',completed_at=1,updated_at=1 WHERE run_id=?", (run_id,))

        await self.engine.delete_rule(rule.id)

        with self.assertRaises(KeyError):
            await self.engine.get_rule(rule.id)
        self.assertEqual(await self.engine.list_rules(), [])
        row = await self.storage.fetchone("SELECT enabled,deleted_at FROM automation_rules WHERE id=?", (rule.id,))
        self.assertEqual(row[0], 0)
        self.assertIsNotNone(row[1])
        history = await self.storage.fetchone("SELECT rule_id,state FROM automation_runs WHERE run_id=?", (run_id,))
        self.assertEqual(tuple(history), (rule.id, "COMPLETED"))
        audit = await self.storage.fetchone("SELECT COUNT(*) FROM audit_events WHERE kind='AUTOMATION_RULE_DELETE' AND subject_id=?", (rule.id,))
        self.assertEqual(audit[0], 1)

    async def test_delete_rejects_active_run_and_keeps_live_rule(self):
        rule = await self._rule(rule_id="active-delete")
        accepted = await self.engine.trigger({"event_id": "active-event", "event_type": "MESSAGE_NEW", "source_peer": "123", "entity_id": 7, "message_id": 9, "payload": {"text": "hello there"}})
        self.assertEqual(accepted, 1)
        run_id = self.jobs.enqueued[0][1]["run_id"]

        with self.assertRaises(AutomationError):
            await self.engine.delete_rule(rule.id)

        self.assertEqual((await self.engine.get_rule(rule.id)).id, rule.id)
        state = await self.storage.fetchone("SELECT state FROM automation_runs WHERE run_id=?", (run_id,))
        self.assertIn(state[0], {"ENQUEUE_PENDING", "QUEUED", "RUNNING", "RECOVERY_REQUIRED"})

    async def test_deleted_rule_can_be_recreated_without_losing_history(self):
        rule = await self._rule(rule_id="recreate-me")
        accepted = await self.engine.trigger({"event_id": "history-event", "event_type": "MESSAGE_NEW", "source_peer": "123", "entity_id": 7, "message_id": 9, "payload": {"text": "hello there"}})
        self.assertEqual(accepted, 1)
        run_id = self.jobs.enqueued[0][1]["run_id"]
        await self.storage.execute("UPDATE automation_runs SET state='COMPLETED',completed_at=1,updated_at=1 WHERE run_id=?", (run_id,))
        await self.engine.delete_rule(rule.id)

        recreated = await self._rule(rule_id="recreate-me", actions=[{"type": "TAG", "tag": "new-version"}])
        self.assertEqual(recreated.version, rule.version + 1)
        self.assertEqual(recreated.actions[0]["tag"], "new-version")
        history = await self.storage.fetchone("SELECT COUNT(*) FROM automation_runs WHERE rule_id=?", (rule.id,))
        self.assertEqual(history[0], 1)
