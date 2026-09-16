from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.services.automation import AUTOMATION_JOB_TYPE, AutomationEngine, AutomationError
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
        self.assertEqual(version[0], 1)

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
