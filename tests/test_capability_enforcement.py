"""Phase 4 capability-core contract tests (tests-first)."""

import asyncio
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from core.plugins.manager import PluginManager
from core.services.jobs import JobEngine
from core.tasks import TaskSupervisor

from core.plugins.capabilities import (
    CAPABILITIES,
    CapabilityDeniedError,
    CapabilityRuntime,
    CapabilityGrantStore,
    current_identity,
    plugin_identity_context,
    trusted_core_context,
    validate_capabilities,
)
from core.services.storage import MIGRATIONS, StorageService


class CapabilityVocabularyTests(unittest.TestCase):
    def test_vocabulary_contains_exactly_the_approved_eleven(self):
        self.assertEqual(
            CAPABILITIES,
            frozenset(
                {
                    "telegram.read",
                    "telegram.write",
                    "network.external",
                    "fs.read",
                    "fs.write",
                    "subprocess",
                    "jobs.enqueue",
                    "ai.remote",
                    "ai.local",
                    "vault.read",
                    "vault.write",
                }
            ),
        )

    def test_vocabulary_validation_rejects_unknown_names(self):
        self.assertEqual(
            validate_capabilities(("telegram.read", "jobs.enqueue")),
            ("telegram.read", "jobs.enqueue"),
        )
        with self.assertRaises(ValueError):
            validate_capabilities(("intel.write",))
        with self.assertRaises(ValueError):
            validate_capabilities(("telegram.read", "telegram.read"))


class CapabilityCoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = StorageService(self.root)
        await self.storage.start()
        self.grants = CapabilityGrantStore(self.storage)
        self.runtime = CapabilityRuntime(self.grants, self.storage)

    async def asyncTearDown(self):
        await self.storage.close()
        self.tmp.cleanup()

    async def _replace_grants(self, *args, **kwargs):
        with trusted_core_context("test.owner-grant"):
            return await self.grants.replace_grants(*args, **kwargs)

    async def test_grant_store_persists_and_migration_is_additive_idempotent(self):
        original = await self.storage.fetchone(
            "SELECT COUNT(*) FROM jobs"
        )
        await self._replace_grants(
            "plugins.readonly", ("telegram.read",), granted_by="owner"
        )
        await self.storage.close()
        await self.storage.start()
        self.grants = CapabilityGrantStore(self.storage)
        self.assertEqual(
            await self.grants.get_grants("plugins.readonly"),
            frozenset({"telegram.read"}),
        )
        await self.storage.close()
        await self.storage.start()
        migrations = await self.storage.fetchall(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        self.assertEqual([row[0] for row in migrations], list(range(1, 14)))
        self.assertEqual(
            (await self.storage.fetchone("SELECT COUNT(*) FROM jobs"))[0],
            original[0],
        )

    async def test_effective_grants_are_declared_intersect_approved(self):
        await self._replace_grants(
            "plugins.example",
            ("telegram.read", "jobs.enqueue"),
            granted_by="owner",
        )
        effective = await self.runtime.load_plugin(
            "plugins.example",
            declared=("telegram.read",),
            mode="ENFORCED",
        )
        self.assertEqual(effective, frozenset({"telegram.read"}))
        await self.runtime.load_plugin(
            "plugins.declared_only",
            declared=("telegram.read",),
            mode="ENFORCED",
        )
        with self.assertRaises(CapabilityDeniedError):
            await self.runtime.authorize(
                "plugins.declared_only", "telegram.read", "test.read"
            )
        await self._replace_grants(
            "plugins.approved_only", ("telegram.read",), granted_by="owner"
        )
        await self.runtime.load_plugin(
            "plugins.approved_only", declared=(), mode="ENFORCED"
        )
        with self.assertRaises(CapabilityDeniedError):
            await self.runtime.authorize(
                "plugins.approved_only", "telegram.read", "test.read"
            )

    async def test_grant_mutation_invalidates_cache_before_next_call(self):
        await self._replace_grants(
            "plugins.cache", ("telegram.read",), granted_by="owner"
        )
        await self.runtime.load_plugin(
            "plugins.cache", declared=("telegram.read",), mode="ENFORCED"
        )
        await self.runtime.authorize("plugins.cache", "telegram.read", "first")
        await self._replace_grants(
            "plugins.cache", (), granted_by="owner"
        )
        with patch.object(self.storage, "fetchall", side_effect=AssertionError("hot path read")):
            with self.assertRaises(CapabilityDeniedError):
                await self.runtime.authorize(
                    "plugins.cache", "telegram.read", "after-revoke"
                )

    async def test_protected_call_does_not_read_grants_from_storage(self):
        await self._replace_grants(
            "plugins.hotpath", ("telegram.read",), granted_by="owner"
        )
        await self.runtime.load_plugin(
            "plugins.hotpath", declared=("telegram.read",), mode="ENFORCED"
        )
        with patch.object(self.storage, "fetchall", side_effect=AssertionError("hot path read")):
            await self.runtime.authorize(
                "plugins.hotpath", "telegram.read", "hotpath.read"
            )

    async def test_plugin_identity_cannot_mutate_grant_store(self):
        with plugin_identity_context("plugins.attacker"):
            with self.assertRaises(PermissionError):
                await self.grants.replace_grants(
                    "plugins.attacker", ("fs.write",), granted_by="owner"
                )


    async def test_fake_plugin_denial_happens_before_side_effect(self):
        await self.runtime.load_plugin(
            "plugins.no_grants", declared=(), mode="ENFORCED"
        )
        effects = []

        async def protected_operation():
            await self.runtime.authorize(
                "plugins.no_grants", "jobs.enqueue", "jobs.enqueue"
            )
            effects.append("created")

        with self.assertRaises(CapabilityDeniedError):
            await protected_operation()
        self.assertEqual(effects, [])

    async def test_audit_records_granted_and_denied_without_secrets(self):
        await self._replace_grants(
            "plugins.audit", ("telegram.read",), granted_by="owner"
        )
        await self.runtime.load_plugin(
            "plugins.audit", declared=("telegram.read",), mode="ENFORCED"
        )
        await self.runtime.authorize(
            "plugins.audit", "telegram.read", "test.read"
        )
        with self.assertRaises(CapabilityDeniedError):
            await self.runtime.authorize(
                "plugins.audit", "jobs.enqueue", "test.enqueue",
                details={"token": "must-not-be-stored", "payload": "private"},
            )
        rows = await self.storage.fetchall(
            "SELECT kind, subject_id, payload_json FROM audit_events "
            "WHERE kind='CAPABILITY_CHECK' ORDER BY id"
        )
        self.assertEqual(len(rows), 2)
        records = [json.loads(row[2]) for row in rows]
        self.assertEqual([item["outcome"] for item in records], ["GRANTED", "DENIED"])
        self.assertTrue(all(item["plugin"] == "plugins.audit" for item in records))
        self.assertEqual(records[0]["capability"], "telegram.read")
        self.assertEqual(records[0]["operation"], "test.read")
        self.assertEqual(records[1]["capability"], "jobs.enqueue")
        self.assertEqual(records[1]["operation"], "test.enqueue")
        self.assertTrue(all(records_item["correlation_id"] for records_item in records))
        self.assertTrue(all(records_item["enforcement_mode"] == "ENFORCED" for records_item in records))
        self.assertTrue(all("must-not-be-stored" not in row[2] for row in rows))
        self.assertTrue(all("private" not in row[2] for row in rows))

    async def test_trusted_core_identity_is_explicit_and_plugin_identity_is_not_core(self):
        self.assertIsNone(current_identity())
        with trusted_core_context("test.framework"):
            identity = current_identity()
            self.assertEqual(identity.kind, "trusted_core")
            self.assertEqual(identity.name, "test.framework")
        self.assertIsNone(current_identity())

    async def test_helper_denies_plugin_and_allows_core_without_service_enforcement(self):
        await self.runtime.load_plugin(
            "plugins.empty", declared=(), mode="ENFORCED"
        )
        with self.assertRaises(CapabilityDeniedError):
            await self.runtime.authorize("plugins.empty", "fs.write", "fs.write")
        with trusted_core_context("test.framework"):
            result = await self.runtime.authorize(
                "core", "fs.write", "framework.fs.write"
            )
        self.assertIsNone(result)



    async def test_background_task_runs_under_explicit_trusted_core_identity(self):
        seen = asyncio.Event()
        identities = []

        async def background():
            identities.append(current_identity())
            await self.runtime.authorize("core", "fs.write", "background.internal")
            seen.set()

        supervisor = TaskSupervisor()
        supervisor.create_task(background(), name="phase4.core.background")
        await asyncio.wait_for(seen.wait(), timeout=1)
        await supervisor.shutdown()
        self.assertEqual(identities[0].kind, "trusted_core")
        self.assertEqual(identities[0].name, "phase4.core.background")

    async def test_job_worker_preserves_core_and_plugin_handler_identity(self):
        engine = JobEngine(self.storage, poll_seconds=0.01)
        core_seen = asyncio.Event()
        plugin_seen = asyncio.Event()
        identities = {}

        await self._replace_grants(
            "plugins.phase4", ("telegram.read",), granted_by="owner"
        )
        await self.runtime.load_plugin(
            "plugins.phase4", declared=("telegram.read",), mode="ENFORCED"
        )

        async def core_handler(_job):
            identities["core"] = current_identity()
            await self.runtime.authorize("core", "fs.write", "job.worker.internal")
            core_seen.set()
            return {"ok": True}

        async def plugin_handler(_job):
            identities["plugin"] = current_identity()
            await self.runtime.authorize(
                "plugins.phase4", "telegram.read", "plugin.handler"
            )
            plugin_seen.set()
            return {"ok": True}

        with trusted_core_context("job.registration"):
            engine.register_handler("PHASE4_CORE", core_handler)
        with plugin_identity_context("plugins.phase4"):
            engine.register_handler("PHASE4_PLUGIN", plugin_handler)
        core_job = await engine.enqueue("PHASE4_CORE")
        plugin_job = await engine.enqueue("PHASE4_PLUGIN")
        await engine.start()
        try:
            await asyncio.wait_for(core_seen.wait(), timeout=1)
            await asyncio.wait_for(plugin_seen.wait(), timeout=1)
            async def wait_completed(job_id):
                for _ in range(100):
                    if (await engine.get(job_id)).state.value == "COMPLETED":
                        return
                    await asyncio.sleep(0.01)
                raise AssertionError(f"job did not complete: {job_id}")
            await wait_completed(core_job.id)
            await wait_completed(plugin_job.id)
        finally:
            await engine.close()
        self.assertEqual(identities["core"].kind, "trusted_core")
        self.assertEqual(identities["plugin"].kind, "plugin")
        self.assertEqual(identities["plugin"].name, "plugins.phase4")
        self.assertEqual((await engine.get(core_job.id)).state.value, "COMPLETED")
        self.assertEqual((await engine.get(plugin_job.id)).state.value, "COMPLETED")

    async def test_command_registry_uses_core_identity_for_framework_and_plugin_for_handler(self):
        from core import registry
        from core.plugins.manager import PluginManager
        from core.context import ApplicationContext

        observations = []
        class Metrics:
            def increment(self, _name):
                observations.append(("framework", current_identity()))
            def timer(self, _name):
                return nullcontext()

        class Context:
            def get(self, name):
                return Metrics() if name == "metrics" else None

        class Client:
            def add_event_handler(self, *_args, **_kwargs):
                return None
            def remove_event_handler(self, *_args, **_kwargs):
                return None

        class Event:
            out = True
            async def edit(self, *_args, **_kwargs):
                return None

        client = Client()
        manager = PluginManager(client, Path(self.tmp.name) / "plugins")
        await self._replace_grants(
            "plugins.phase4-command", ("telegram.read",), granted_by="owner"
        )
        await self.runtime.load_plugin(
            "plugins.phase4-command",
            declared=("telegram.read",),
            mode="ENFORCED",
        )
        async def handler(_event):
            await self.runtime.authorize(
                "plugins.phase4-command", "telegram.read", "command.handler"
            )
            observations.append(("handler", current_identity()))

        with PluginManager.plugin_context("plugins.phase4-command", manager):
            registration = registry.register_cmd(
                client,
                r"\\.phase4capability",
                handler,
                description="Phase 4 test command",
            )
        try:
            with patch("core.context.get_application_context", return_value=Context()):
                await registration.wrapper(Event())
        finally:
            registration.unregister(client)
        framework_identity = next(value for kind, value in observations if kind == "framework")
        handler_identity = next(value for kind, value in observations if kind == "handler")
        self.assertEqual(framework_identity.kind, "trusted_core")
        self.assertEqual(handler_identity.kind, "plugin")
        self.assertEqual(handler_identity.name, "plugins.phase4-command")



class CapabilityMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_13_is_additive_and_idempotent_for_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "databases" / "platform.db"
            db_path.parent.mkdir(parents=True)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)"
                )
                for version, sql in MIGRATIONS[:12]:
                    for statement in (part.strip() for part in sql.split(";") if part.strip()):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?,?,?)",
                        (version, hashlib.sha256(sql.encode()).hexdigest(), time.time()),
                    )
                conn.execute(
                    "INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES (?,?,?,?)",
                    ("pre-phase4", "preserve-me", '{"existing":true}', 1.0),
                )
                conn.commit()
            finally:
                conn.close()

            storage = StorageService(root)
            await storage.start()
            row = await storage.fetchone(
                "SELECT payload_json FROM audit_events WHERE kind='pre-phase4' AND subject_id='preserve-me'"
            )
            self.assertEqual(row[0], '{"existing":true}')
            self.assertIsNotNone(
                await storage.fetchone(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='plugin_capability_grants'"
                )
            )
            await storage.close()
            await storage.start()
            versions = await storage.fetchall(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
            self.assertEqual([row[0] for row in versions], list(range(1, 14)))
            row = await storage.fetchone(
                "SELECT payload_json FROM audit_events WHERE kind='pre-phase4' AND subject_id='preserve-me'"
            )
            self.assertEqual(row[0], '{"existing":true}')
            await storage.close()


class CapabilityIsolationHonestyTests(unittest.TestCase):
    def test_capability_handles_do_not_sandbox_direct_python_access(self):
        # Capability checks govern the supported API only; direct Python access
        # to imported modules remains possible in this shared process.
        import os

        self.assertTrue(callable(os.getcwd))


if __name__ == "__main__":
    unittest.main()
