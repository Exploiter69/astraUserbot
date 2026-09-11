import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

# Phase 9's compatibility boundary is explicit. Legacy plugins outside this
# migration set are not silently treated as Phase 9 failures; they remain
# candidates for their own migration phase/batch.
PHASE9_BOUNDARY_PATHS = (
    "plugins/network_osint/dns.py",
    "plugins/network_osint/headers.py",
    "plugins/network_osint/ipinfo.py",
    "plugins/network_osint/speedtest.py",
    "plugins/advanced/osint_recon.py",
    "plugins/media/ocr.py",
    "plugins/system/sysinfo.py",
    "plugins/system_ops/doctor.py",
    "plugins/system_ops/testall.py",
    "plugins/backup/cloud_backup.py",
    "plugins/media/ffmpeg.py",
    "plugins/advanced/mediaflow.py",
    "plugins/media_ops/video.py",
    "plugins/media_ops/speech.py",
    "plugins/media_ops/stream.py",
    "plugins/media/aria2.py",
    "plugins/media/rclone.py",
    "plugins/ai_gateway/ask.py",
    "plugins/ai_gateway/summarize.py",
    "plugins/ai_gateway/transcribe.py",
)


class Phase9MigrationGate(unittest.TestCase):
    def _source(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def _tree(self, relative: str) -> ast.AST:
        return ast.parse(self._source(relative), filename=relative)

    def _imports(self, relative: str) -> set[str]:
        tree = self._tree(relative)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.add(f"{module}.{alias.name}")
        return imports

    def test_network_plugins_use_shared_http_service(self):
        for path in (
            "plugins/network_osint/dns.py",
            "plugins/network_osint/headers.py",
            "plugins/network_osint/ipinfo.py",
            "plugins/advanced/osint_recon.py",
        ):
            source = self._source(path)
            self.assertIn("get_application_context", source, path)
            self.assertIn('context.get("http")', source, path)
            self.assertNotIn("get_session", source, path)

    def test_speedtest_uses_shared_subprocess_service(self):
        source = self._source("plugins/network_osint/speedtest.py")
        self.assertIn('context.get("subprocess")', source)
        self.assertIn("subprocess.run", source)
        self.assertNotIn("helpers.shell", source)

    def test_system_plugins_use_shared_subprocess_boundary(self):
        for path in (
            "plugins/system/sysinfo.py",
            "plugins/media/ocr.py",
            "plugins/backup/cloud_backup.py",
            "plugins/system_ops/doctor.py",
        ):
            source = self._source(path)
            self.assertIn('context.get("subprocess")', source, path)
            self.assertNotIn("helpers.shell", source, path)

    def test_media_batch_uses_media_service(self):
        paths = (
            "plugins/media/ffmpeg.py",
            "plugins/advanced/mediaflow.py",
            "plugins/media_ops/video.py",
            "plugins/media_ops/speech.py",
            "plugins/media_ops/stream.py",
            "plugins/media/aria2.py",
            "plugins/media/rclone.py",
        )
        for path in paths:
            source = self._source(path)
            self.assertIn("get_application_context", source, path)
            self.assertIn('context.get("media")', source, path)

    def test_active_ai_gateway_uses_ai_service(self):
        for path in (
            "plugins/ai_gateway/ask.py",
            "plugins/ai_gateway/summarize.py",
            "plugins/ai_gateway/transcribe.py",
        ):
            source = self._source(path)
            self.assertIn("get_application_context", source, path)
            self.assertIn('context.get("ai")', source, path)

    def test_no_phase9_plugin_imports_helpers_shell(self):
        offenders = []
        for relative in PHASE9_BOUNDARY_PATHS:
            source = self._source(relative)
            if "from helpers.shell import run" in source or "import helpers.shell" in source:
                offenders.append(relative)
        self.assertEqual([], offenders)

    def test_no_phase9_plugin_creates_aiohttp_session(self):
        offenders = []
        for relative in PHASE9_BOUNDARY_PATHS:
            source = self._source(relative)
            if "aiohttp.ClientSession" in source or "aiohttp.ClientSession(" in source:
                offenders.append(relative)
        self.assertEqual([], offenders)

    def test_no_plugin_uses_requests_library(self):
        offenders = []
        for relative in PHASE9_BOUNDARY_PATHS:
            imports = self._imports(relative)
            if any(item == "requests" or item.startswith("requests.") for item in imports):
                offenders.append(relative)
        self.assertEqual([], offenders)

    def test_migrated_sources_parse(self):
        paths = (
            "plugins/network_osint/dns.py",
            "plugins/network_osint/headers.py",
            "plugins/network_osint/ipinfo.py",
            "plugins/network_osint/speedtest.py",
            "plugins/advanced/osint_recon.py",
            "plugins/media/ocr.py",
            "plugins/system/sysinfo.py",
            "plugins/system_ops/doctor.py",
            "plugins/system_ops/testall.py",
            "plugins/backup/cloud_backup.py",
        )
        for path in paths:
            self._tree(path)

    def test_phase9_readiness_contract_exists(self):
        readiness = ROOT / "PHASE_9_READINESS.md"
        self.assertTrue(readiness.is_file())
        text = readiness.read_text(encoding="utf-8")
        self.assertIn("Gate 9", text)
        self.assertIn("₹0 / $0", text)
        self.assertIn("Compatibility Exit", text)


if __name__ == "__main__":
    unittest.main()
