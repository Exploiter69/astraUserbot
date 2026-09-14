from __future__ import annotations

import ast
import asyncio
import tempfile
import unittest
from pathlib import Path

from core.context import ApplicationContext
from core.plugins.manager import PluginManager
from core.sdk import PluginMetadata

ROOT = Path(__file__).resolve().parents[1]


class Phase16Gate(unittest.TestCase):

    def test_plugin_audit(self):
        from tools.phase16_audit import FORBIDDEN_IMPORTS, QUARANTINED

        violations = []

        for path in sorted((ROOT / "plugins").rglob("*.py")):
            if path.name == "__init__.py" or path.name.startswith("_"):
                continue

            name = ".".join(path.relative_to(ROOT).with_suffix("").parts)

            if name in QUARANTINED:
                continue

            tree = ast.parse(path.read_text(), filename=str(path))

            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)

            for forbidden in FORBIDDEN_IMPORTS:
                if forbidden in imports or any(
                    item.startswith(forbidden + ".") for item in imports
                ):
                    violations.append((name, forbidden))

        self.assertEqual([], violations)

    def test_groq_client_is_quarantined(self):
        self.assertIn(
            "plugins.ai.groq_client",
            PluginManager._QUARANTINED_MODULES,
        )

    def test_sdk_metadata_contract(self):
        metadata = PluginMetadata(
            name="phase16-test",
            version="1.0.0",
            api_version="1.0",
            dependencies=(),
            capabilities=("test",),
        )

        self.assertEqual(metadata.name, "phase16-test")
        self.assertEqual(metadata.api_version, "1.0")
        self.assertEqual(metadata.capabilities, ("test",))

    def test_application_context_runtime_lifecycle(self):
        async def run():
            context = ApplicationContext(object(), ROOT)

            expected = {
                "storage",
                "cache",
                "http",
                "subprocess",
                "telegram_state",
                "telegram",
                "workspace",
                "media",
                "jobs",
                "secrets",
                "ai",
                "search",
                "metrics",
                "flags",
                "isolation",
            }

            self.assertEqual(set(context.services), expected)

            await context.start()
            self.assertEqual(context.snapshot()["state"], "RUNNING")
            await context.close()
            self.assertEqual(context.snapshot()["state"], "CLOSED")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
