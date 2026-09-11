import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path

from core.plugins.manager import (
    PluginDependencyError,
    PluginManager,
    PluginState,
)


class PluginManagerTests(unittest.TestCase):
    def test_dependency_order_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(object(), Path(tmp) / "plugins")
            manager.discover()
            manager.records = {
                "plugins.alpha": manager.records.get("plugins.alpha")
                or __import__("core.plugins.manager", fromlist=["PluginRecord"]).PluginRecord(
                    "plugins.alpha", dependencies=("plugins.base",)
                ),
                "plugins.base": __import__("core.plugins.manager", fromlist=["PluginRecord"]).PluginRecord(
                    "plugins.base"
                ),
                "plugins.beta": __import__("core.plugins.manager", fromlist=["PluginRecord"]).PluginRecord(
                    "plugins.beta", dependencies=("plugins.base",)
                ),
            }
            self.assertEqual(
                manager._dependency_order(),
                ["plugins.base", "plugins.alpha", "plugins.beta"],
            )

    def test_unknown_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(object(), Path(tmp) / "plugins")
            from core.plugins.manager import PluginRecord

            manager.records = {
                "plugins.example": PluginRecord(
                    "plugins.example", dependencies=("plugins.missing",)
                )
            }
            with self.assertRaises(PluginDependencyError):
                manager._dependency_order()

    def test_dependency_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(object(), Path(tmp) / "plugins")
            from core.plugins.manager import PluginRecord

            manager.records = {
                "plugins.a": PluginRecord("plugins.a", dependencies=("plugins.b",)),
                "plugins.b": PluginRecord("plugins.b", dependencies=("plugins.a",)),
            }
            with self.assertRaises(PluginDependencyError):
                manager._dependency_order()

    def test_lifecycle_and_shutdown_hooks(self):
        calls = []
        module = types.ModuleType("plugins.lifecycle")

        async def setup(client):
            calls.append("setup")

        async def shutdown(client):
            calls.append("shutdown")

        module.setup = setup
        module.shutdown = shutdown
        sys.modules[module.__name__] = module

        try:
            with tempfile.TemporaryDirectory() as tmp:
                manager = PluginManager(object(), Path(tmp) / "plugins")
                from core.plugins.manager import PluginRecord

                manager.records = {
                    module.__name__: PluginRecord(module.__name__, module=module)
                }
                asyncio.run(manager.load_all())
                self.assertEqual(manager.get(module.__name__).state, PluginState.RUNNING)
                self.assertEqual(calls, ["setup"])

                asyncio.run(manager.shutdown())
                self.assertEqual(manager.get(module.__name__).state, PluginState.UNLOADED)
                self.assertEqual(calls, ["setup", "shutdown"])
        finally:
            sys.modules.pop(module.__name__, None)

    def test_snapshot_contains_only_safe_lifecycle_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(object(), Path(tmp) / "plugins")
            manager.discover()
            manager.records = {}
            from core.plugins.manager import PluginRecord

            manager.records["plugins.example"] = PluginRecord(
                "plugins.example",
                state=PluginState.RUNNING,
                dependencies=("plugins.base",),
                critical=True,
            )
            snapshot = manager.snapshot()
            self.assertEqual(snapshot[0]["state"], "RUNNING")
            self.assertEqual(snapshot[0]["dependencies"], ["plugins.base"])
            self.assertTrue(snapshot[0]["critical"])


if __name__ == "__main__":
    unittest.main()
