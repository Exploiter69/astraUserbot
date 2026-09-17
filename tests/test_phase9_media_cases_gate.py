import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Phase9MediaInvestigationGateTests(unittest.TestCase):
    def test_required_services_and_plugin_exist(self):
        for path in (
            ROOT / "core/services/media_intel.py",
            ROOT / "core/services/cases.py",
            ROOT / "plugins/intelligence/media_cases.py",
        ):
            self.assertTrue(path.is_file(), path)
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_media_intel_uses_existing_boundaries(self):
        source = (ROOT / "core/services/media_intel.py").read_text(encoding="utf-8")
        self.assertIn("self.media.run_isolated", source)
        self.assertIn("self.media.create_workspace", source)
        self.assertIn("self.media.cleanup", source)
        self.assertIn("sha256", source)
        self.assertIn("PHASH_DISTANCE", source)
        self.assertIn("MAX_TEXT", source)
        self.assertNotIn("shell=True", source)

    def test_case_service_is_durable_and_bounded(self):
        source = (ROOT / "core/services/cases.py").read_text(encoding="utf-8")
        self.assertIn("self.storage = intelgraph.storage", source)
        self.assertIn("MAX_ROWS", source)
        self.assertIn("case_timeline", source)
        self.assertIn("case_entities", source)
        self.assertIn("def report", source)

    def test_phase9_commands_are_declared(self):
        source = (ROOT / "plugins/intelligence/media_cases.py").read_text(encoding="utf-8")
        for command in ("mediaintel", "mediasim", "case"):
            self.assertIn(command, source)
        self.assertIn("bounded", source.lower())

    def test_no_new_network_or_shell_dependency(self):
        for relative in (
            "core/services/media_intel.py",
            "core/services/cases.py",
            "plugins/intelligence/media_cases.py",
        ):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {node.module or ""}
                else:
                    continue
                self.assertNotIn("requests", names)
                self.assertNotIn("httpx", names)
                self.assertNotIn("subprocess", names)
                self.assertNotIn("aiohttp", names)


if __name__ == "__main__":
    unittest.main()
