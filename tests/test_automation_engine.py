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
        self.assertEqual(self.jobs.enqueued[0][1]["run_id"], (await self.storage.fetchone("SELECT run_id FROM automation_runs LIMIT 1"))[0])

    async def test_scope_mismatch_does_not_enqueue(self):
        await self._rule()
        accepted = await self.engine.trigger({"event_id": "e2", "event_type": "MESSAGE_NEW", "source_peer": "999", "payload": {"text": "hello"}})
        self.assertEqual(accepted, 0)
        self.assertEqual(self.jobs.enqueued, [])

    async def test_cooldown_is_durable(self):
        await self._rule(cooldown_seconds=60)
        event = {"event_id": "e3", "event_type": "MESSAGE_NEW", "source_peer": "123", "payload": {"text": "hello"}}
        self.assertEqual(await self.engine.trigger(event), 1)
        self.assertEqual(await self.engine.trigger(event), 0)
        self.assertEqual(len(self.jobs.enqueued), 1)

    async def test_disabled_rule_does_not_trigger(self):
        await self._rule()
        await self.engine.set_enabled("hello", False)
        accepted = await self.engine.trigger({"event_id": "e4", "event_type": "MESSAGE_NEW", "source_peer": "123", "payload": {"text": "hello"}})
        self.assertEqual(accepted, 0)

    async def test_owner_command_targets_only_selected_rule(self):
        await self._rule(rule_id="one", trigger={"type": "OWNER_COMMAND"}, scope={"owner": "42"}, match={}, actions=[{"type": "TAG", "tag": "one"}])
        await self._rule(rule_id="two", trigger={"type": "OWNER_COMMAND"}, scope={"owner": "42"}, match={}, actions=[{"type": "TAG", "tag": "two"}])
        accepted = await self.engine.run_owner_command("one", {"source_peer": "42"})
        self.assertEqual(accepted, 1)
        self.assertEqual(self.jobs.enqueued[0][1]["rule_id"], "one")

    async def test_multi_step_run_persists_step_boundaries(self):
        rule = await self._rule(actions=[{"type": "TAG", "tag": "a"}, {"type": "INDEX", "tag": "b"}])
        job = Job("job", AUTOMATION_JOB_TYPE, JobState.RUNNING, {"run_id": "run", "rule_id": rule.id, "rule_version": rule.version, "event": {"event_id": "e", "event_type": "MESSAGE_NEW", "source_peer": "123", "payload": {"text": "hello"}}}, None, None, None, "42", None, 1, 3, 0, "automation", 2, False)
        await self.storage.execute("INSERT INTO automation_runs(run_id,rule_id,rule_version,trigger_event_id,trigger_type,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("run", rule.id, rule.version, "e", "MESSAGE_NEW", "QUEUED", 0, 0))
        result = await self.engine._handle_job(job)
        self.assertEqual(result["state"], "COMPLETED")
        states = await self.storage.fetchall("SELECT state FROM automation_action_runs WHERE run_id=? ORDER BY action_index", ("run",))
        self.assertEqual([row[0] for row in states], ["COMPLETED", "COMPLETED"])
        audits = await self.storage.fetchall("SELECT kind FROM audit_events WHERE subject_id=? ORDER BY id", ("run",))
        self.assertTrue(any(row[0] == "ACTION_STARTED" for row in audits))
        self.assertTrue(any(row[0] == "STEP_COMPLETED" for row in audits))

    async def test_stale_rule_version_is_rejected(self):
        rule = await self._rule()
        job = Job("job", AUTOMATION_JOB_TYPE, JobState.RUNNING, {"run_id": "run", "rule_id": rule.id, "rule_version": rule.version - 1, "event": {}}, None, None, None, "42", None, 1, 3, 0, "automation", 2, False)
        with self.assertRaises(JobError) as ctx:
            await self.engine._handle_job(job)
        self.assertEqual(ctx.exception.code, "AUTOMATION_RULE_VERSION_STALE")

    async def test_reply_action_uses_telegram_facade(self):
        rule = await self._rule()
        job = Job("job", AUTOMATION_JOB_TYPE, JobState.RUNNING, {"run_id": "run", "rule_id": rule.id, "rule_version": rule.version, "event": {"event_id": "e", "event_type": "MESSAGE_NEW", "source_peer": "123", "message_id": 9, "payload": {"text": "hello"}}}, None, None, None, "42", None, 1, 3, 0, "automation", 2, False)
        await self.storage.execute("INSERT INTO automation_runs(run_id,rule_id,rule_version,trigger_event_id,trigger_type,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("run", rule.id, rule.version, "e", "MESSAGE_NEW", "QUEUED", 0, 0))
        await self.engine._handle_job(job)
        self.assertEqual(self.telegram.sent[0][0], 123)
        self.assertEqual(self.telegram.sent[0][1], "world")
        self.assertEqual(self.telegram.sent[0][2]["reply_to"], 9)

    async def test_start_job_requires_registered_handler(self):
        await self._rule(actions=[{"type": "START_JOB", "job_type": "SAFE_JOB", "payload": {"x": 1}}])
        with self.assertRaises(JobError):
            job = Job("job", AUTOMATION_JOB_TYPE, JobState.RUNNING, {"run_id": "run", "rule_id": "hello", "rule_version": 1, "event": {"event_id": "e"}}, None, None, None, "42", None, 1, 3, 0, "automation", 2, False)
            await self.storage.execute("INSERT INTO automation_runs(run_id,rule_id,rule_version,trigger_event_id,trigger_type,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("run", "hello", 1, "e", "OWNER_COMMAND", "QUEUED", 0, 0))
            await self.engine._handle_job(job)

    async def test_plugin_action_must_be_explicitly_registered(self):
        await self._rule(actions=[{"type": "PLUGIN_ACTION", "name": "missing"}])
        job = Job("job", AUTOMATION_JOB_TYPE, JobState.RUNNING, {"run_id": "run", "rule_id": "hello", "rule_version": 1, "event": {"event_id": "e"}}, None, None, None, "42", None, 1, 3, 0, "automation", 2, False)
        await self.storage.execute("INSERT INTO automation_runs(run_id,rule_id,rule_version,trigger_event_id,trigger_type,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("run", "hello", 1, "e", "OWNER_COMMAND", "QUEUED", 0, 0))
        with self.assertRaises(JobError):
            await self.engine._handle_job(job)

    async def test_delete_is_blocked_while_run_is_active(self):
        await self._rule()
        await self.storage.execute("INSERT INTO automation_runs(run_id,rule_id,rule_version,trigger_event_id,trigger_type,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("run", "hello", 1, "e", "MESSAGE_NEW", "QUEUED", 0, 0))
        with self.assertRaises(AutomationError):
            await self.engine.delete_rule("hello")
        await self.engine.set_enabled("hello", False)
        rule = await self.engine.get_rule("hello")
        self.assertFalse(rule.enabled)

    async def test_action_handler_registration_is_explicit(self):
        seen = []

        async def handler(action, event):
            seen.append((action["name"], event["event_id"]))
            return {"ok": True}

        self.engine.register_action_handler("PLUGIN_ACTION", handler)
        rule = await self._rule(actions=[{"type": "PLUGIN_ACTION", "name": "demo"}])
        job = Job("job", AUTOMATION_JOB_TYPE, JobState.RUNNING, {"run_id": "run", "rule_id": rule.id, "rule_version": rule.version, "event": {"event_id": "e"}}, None, None, None, "42", None, 1, 3, 0, "automation", 2, False)
        await self.storage.execute("INSERT INTO automation_runs(run_id,rule_id,rule_version,trigger_event_id,trigger_type,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("run", rule.id, rule.version, "e", "OWNER_COMMAND", "QUEUED", 0, 0))
        await self.engine._handle_job(job)
        self.assertEqual(seen, [("demo", "e")])

    async def test_job_completion_trigger_is_supported(self):
        await self._rule(rule_id="done", trigger={"type": "JOB_COMPLETED"}, scope={"job_type": "SAFE"}, match={"job_type": "SAFE"}, actions=[{"type": "TAG", "tag": "done"}])
        job = Job("other", "SAFE", JobState.COMPLETED, {}, {"ok": True}, None, None, "42", None, 1, 1, 1, "default", 0, False)
        accepted = await self.engine.handle_job_completion(job)
        self.assertEqual(accepted, 1)
        self.assertEqual(self.jobs.enqueued[0][1]["event"]["payload"]["job_type"], "SAFE")

    async def test_rule_schema_never_accepts_arbitrary_code(self):
        with self.assertRaises(AutomationError):
            await self._rule(actions=[{"type": "EXECUTE_PYTHON", "code": "__import__('os').system('x')"}])


if __name__ == "__main__":
    unittest.main()
