"""Integration checks for the Phase 1 platform gate."""

from __future__ import annotations

import asyncio
import importlib
import unittest
from pathlib import Path
from unittest.mock import patch

from core.errors import AstraError, ErrorCode, as_astra_error, user_message
from core.plugins.manager import PluginManager, PluginState
from core.registry import COMMANDS, clear_registrations, list_registrations
from core.tasks import TaskSupervisor, TaskState


class FakeDB:
    async def init_schema(self, _sql: str) -> None:
        return None


class FakeClient:
    def __init__(self) -> None:
        self.handlers: list[tuple[object, object]] = []
        self.plugin_manager = None

    def add_event_handler(self, callback, event) -> None:
        self.handlers.append((callback, event))

    def remove_event_handler(self, callback, event) -> None:
        self.handlers = [item for item in self.handlers if item != (callback, event)]


class Phase1GateTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        # Keep global registry state isolated even if a test fails midway.
        self._clear_registry()

    @staticmethod
    def _clear_registry() -> None:
        client = FakeClient()
        clear_registrations(client)

    async def test_real_plugin_tree_is_discoverable_deterministically(self) -> None:
        root = Path(__file__).resolve().parent.parent / "plugins"
        manager = PluginManager(FakeClient(), root)
        records = manager.discover()

        self.assertGreater(len(records), 0)
        names = [record.name for record in records]
        self.assertEqual(names, sorted(names))
        self.assertIn("plugins.security.acl", names)
        self.assertIn("plugins.security.pmguard", names)

    async def test_real_block_unblock_collision_is_rejected(self) -> None:
        client = FakeClient()
        manager = PluginManager(client, Path(__file__).resolve().parent.parent / "plugins")
        client.plugin_manager = manager
        manager.discover()

        acl = importlib.import_module("plugins.security.acl")
        pmguard = importlib.import_module("plugins.security.pmguard")
        acl.db = FakeDB()
        pmguard.db = FakeDB()

        await acl.setup(client)
        self.assertEqual(len(list_registrations()), 1)
        self.assertEqual(manager.get("plugins.security.acl").registrations.__len__(), 1)

        with self.assertRaises(ValueError):
            await pmguard.setup(client)

        # The first registration remains intact; collision handling is atomic.
        self.assertEqual(len(list_registrations()), 1)
        self.assertIn(next(iter(COMMANDS)), COMMANDS)

    async def test_plugin_manager_reports_setup_failure_truthfully(self) -> None:
        class BadPlugin:
            async def setup(_client):
                raise RuntimeError("internal setup detail")

        manager = PluginManager(FakeClient(), Path("/tmp/nonexistent"))
        manager.records = {
            "bad": type("Record", (), {
                "name": "bad",
                "module": BadPlugin,
                "state": PluginState.LOADED,
                "dependencies": (),
                "critical": False,
                "error": None,
                "registrations": set(),
            })()
        }
        await manager.load_all()
        record = manager.get("bad")
        self.assertEqual(record.state, PluginState.FAILED_SETUP)
        self.assertEqual(record.error, "internal setup detail")

    async def test_safe_errors_hide_unexpected_details(self) -> None:
        error = as_astra_error(
            RuntimeError("/secret/provider/path"),
            operation="phase1-gate",
            component="test",
            correlation_id="gate123",
        )
        self.assertIsInstance(error, AstraError)
        self.assertEqual(error.code, ErrorCode.UNKNOWN)
        message = user_message(error)
        self.assertNotIn("/secret/provider/path", message)
        self.assertLessEqual(len(message), 500)

    async def test_task_supervisor_failure_isolated_and_archived(self) -> None:
        supervisor = TaskSupervisor(history_limit=4)

        async def crash() -> None:
            raise RuntimeError("secret provider response")

        task = supervisor.create_task(crash(), name="phase1.gate.crash")
        with self.assertRaises(RuntimeError):
            await task
        await asyncio.sleep(0)

        record = supervisor.history()[-1]
        self.assertEqual(record.state, TaskState.FAILED)
        self.assertEqual(record.error_code, ErrorCode.UNKNOWN.value)
        await supervisor.shutdown()

    async def test_plugin_shutdown_removes_owned_registrations(self) -> None:
        client = FakeClient()
        manager = PluginManager(client, Path(__file__).resolve().parent.parent / "plugins")
        client.plugin_manager = manager
        manager.discover()

        acl = importlib.import_module("plugins.security.acl")
        acl.db = FakeDB()
        manager.records["plugins.security.acl"].module = acl
        manager.records["plugins.security.acl"].state = PluginState.LOADED
        manager._load_order = ["plugins.security.acl"]
        await acl.setup(client)
        manager.records["plugins.security.acl"].state = PluginState.RUNNING

        self.assertEqual(len(list_registrations()), 1)
        await manager.shutdown()
        self.assertEqual(len(list_registrations()), 0)
        self.assertEqual(manager.get("plugins.security.acl").state, PluginState.UNLOADED)
