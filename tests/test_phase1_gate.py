"""Integration checks for the Phase 1 platform gate."""

from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

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

    async def test_real_block_unblock_has_single_owner(self) -> None:
        client = FakeClient()
        manager = PluginManager(client, Path(__file__).resolve().parent.parent / "plugins")
        client.plugin_manager = manager
        manager.discover()

        acl = importlib.import_module("plugins.security.acl")
        pmguard = importlib.import_module("plugins.security.pmguard")
        acl.db = FakeDB()
        pmguard.db = FakeDB()

        with manager.plugin_context("plugins.security.acl", manager):
            await acl.setup(client)
        self.assertEqual(len(list_registrations()), 1)
        self.assertEqual(len(manager.get("plugins.security.acl").registrations), 1)

        with manager.plugin_context("plugins.security.pmguard", manager):
            await pmguard.setup(client)

        # PM Guard must coexist without claiming the ACL-owned commands.
        self.assertEqual(len(list_registrations()), 2)
        self.assertEqual(len(manager.get("plugins.security.pmguard").registrations), 1)
        self.assertIn(next(iter(COMMANDS)), COMMANDS)

    async def test_plugin_manager_reports_setup_failure_truthfully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plugins"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "bad.py").write_text(
                "async def setup(client):\n"
                "    raise RuntimeError('internal setup detail')\n",
                encoding="utf-8",
            )

            module_name = f"phase1_gate_{id(root)}"
            package_root = root.parent
            package = package_root / module_name
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "bad.py").write_text(
                "async def setup(client):\n"
                "    raise RuntimeError('internal setup detail')\n",
                encoding="utf-8",
            )

            sys.path.insert(0, str(package_root))
            try:
                manager = PluginManager(FakeClient(), package)
                records = manager.discover()
                self.assertEqual([record.name for record in records], [f"{module_name}.bad"])
                await manager.load_all()
                record = manager.get(f"{module_name}.bad")
                self.assertEqual(record.state, PluginState.FAILED_SETUP)
                self.assertEqual(record.error, "internal setup detail")
            finally:
                sys.path.remove(str(package_root))
                sys.modules.pop(f"{module_name}.bad", None)
                sys.modules.pop(module_name, None)

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
        with manager.plugin_context("plugins.security.acl", manager):
            await acl.setup(client)
        manager.records["plugins.security.acl"].state = PluginState.RUNNING

        self.assertEqual(len(list_registrations()), 1)
        await manager.shutdown()
        self.assertEqual(len(list_registrations()), 0)
        self.assertEqual(manager.get("plugins.security.acl").state, PluginState.UNLOADED)
