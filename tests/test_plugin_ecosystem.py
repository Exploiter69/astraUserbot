import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path

from core.plugins.contract import PLUGIN_API_VERSION, metadata_for
from core.plugins.manager import PluginDependencyError, PluginLifecycleError, PluginManager, PluginRecord, PluginState


class PluginEcosystemTests(unittest.TestCase):
    def test_legacy_module_gets_deterministic_contract_defaults(self):
        module = types.ModuleType("plugins.legacy_contract")
        module.setup = lambda client: None
        metadata = metadata_for(module)
        self.assertEqual(metadata.name, "plugins.legacy_contract")
        self.assertEqual(metadata.version, "legacy")
        self.assertEqual(metadata.api_version, PLUGIN_API_VERSION)
        self.assertEqual(metadata.dependencies, ())

    def test_explicit_metadata_is_normalized(self):
        module = types.ModuleType("plugins.explicit_contract")
        module.plugin_name = "plugins.explicit_contract"
        module.plugin_version = "2.1.0"
        module.plugin_api_version = PLUGIN_API_VERSION
        module.plugin_description = "Example plugin"
        module.dependencies = ("plugins.base",)
        module.optional_dependencies = ("plugins.optional",)
        module.capabilities = ("telegram.read", "media.process")
        module.critical = True
        metadata = metadata_for(module)
        self.assertEqual(metadata.version, "2.1.0")
        self.assertEqual(metadata.dependencies, ("plugins.base",))
        self.assertEqual(metadata.capabilities, ("telegram.read", "media.process"))
        self.assertTrue(metadata.critical)

    def test_metadata_rejects_wrong_api_version(self):
        module = types.ModuleType("plugins.bad_contract")
        module.plugin_api_version = PLUGIN_API_VERSION + 1
        with self.assertRaises(ValueError):
            metadata_for(module)

    def test_disable_is_transactional_and_unregisters_owned_commands(self):
        module = types.ModuleType("plugins.disable_contract")
        module.setup = lambda client: None
        module.shutdown = lambda client: None
        sys.modules[module.__name__] = module
        try:
            with tempfile.TemporaryDirectory() as tmp:
                manager = PluginManager(object(), Path(tmp) / "plugins")
                manager.records = {module.__name__: PluginRecord(module.__name__, module=module, state=PluginState.RUNNING)}
                manager._load_order = [module.__name__]
                result = asyncio.run(manager.disable_plugin(module.__name__))
                self.assertEqual(result.state, PluginState.DISABLED)
        finally:
            sys.modules.pop(module.__name__, None)

    def test_disable_refuses_running_dependents(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(object(), Path(tmp) / "plugins")
            manager.records = {
                "plugins.base": PluginRecord("plugins.base", state=PluginState.RUNNING),
                "plugins.child": PluginRecord("plugins.child", dependencies=("plugins.base",), state=PluginState.RUNNING),
            }
            with self.assertRaises(PluginDependencyError):
                asyncio.run(manager.disable_plugin("plugins.base"))

    def test_enable_refuses_quarantined_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(object(), Path(tmp) / "plugins")
            manager.records = {
                "plugins.ai.ask": PluginRecord("plugins.ai.ask", state=PluginState.DISABLED)
            }
            with self.assertRaises(PluginLifecycleError):
                asyncio.run(manager.enable_plugin("plugins.ai.ask"))

    def test_enable_rolls_back_failed_setup(self):
        module = types.ModuleType("plugins.enable_contract")
        def setup(client):
            raise RuntimeError("setup failed")
        module.setup = setup
        sys.modules[module.__name__] = module
        try:
            with tempfile.TemporaryDirectory() as tmp:
                manager = PluginManager(object(), Path(tmp) / "plugins")
                manager.records = {module.__name__: PluginRecord(module.__name__, module=module, state=PluginState.DISABLED)}
                manager._disabled.add(module.__name__)
                with self.assertRaises(PluginLifecycleError):
                    asyncio.run(manager.enable_plugin(module.__name__))
                self.assertEqual(manager.get(module.__name__).state, PluginState.FAILED_SETUP)
                self.assertIn(module.__name__, manager._disabled)
        finally:
            sys.modules.pop(module.__name__, None)

    def test_snapshot_exposes_contract_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(object(), Path(tmp) / "plugins")
            manager.records = {
                "plugins.example": PluginRecord(
                    "plugins.example", state=PluginState.RUNNING, version="1.0.0",
                    api_version=1, description="Example", optional_dependencies=("plugins.opt",),
                    capabilities=("telegram.read",),
                )
            }
            row = manager.snapshot()[0]
            self.assertEqual(row["version"], "1.0.0")
            self.assertEqual(row["optional_dependencies"], ["plugins.opt"])
            self.assertEqual(row["capabilities"], ["telegram.read"])


if __name__ == "__main__":
    unittest.main()
