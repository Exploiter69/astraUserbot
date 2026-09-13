import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins"
QUARANTINED = {
    "plugins.ai.ask",
    "plugins.ai.groq_client",
    "plugins.ai.summarize",
    "plugins.ai.transcribe",
}
SKIP = {"__pycache__", ".git", ".venv", "venv", "env", ".pytest_cache"}
ALLOWED_DIRECT_EVENTS = {
    Path("plugins/security/account_archiver.py"),
    Path("plugins/security/acl.py"),
    Path("plugins/security/logger.py"),
    Path("plugins/security/pmguard.py"),
    Path("plugins/system/afk.py"),
}


def active_files():
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        if any(part in SKIP for part in path.parts):
            continue
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        if module not in QUARANTINED:
            yield path


class PluginBehaviorContractTests(unittest.TestCase):
    def test_every_active_plugin_parses(self):
        for path in active_files():
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_active_plugins_do_not_bypass_shared_network_or_subprocess_boundaries(self):
        forbidden_imports = {"requests", "httpx", "urllib.request", "subprocess", "aiohttp", "helpers.shell", "helpers.net"}
        for path in active_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {node.module or ""}
                else:
                    continue
                self.assertTrue(
                    not any(name in forbidden_imports or any(name.startswith(item + ".") for item in forbidden_imports) for name in names),
                    f"{path.relative_to(ROOT)} bypasses a shared boundary: {names}",
                )

    def test_direct_incoming_handlers_are_explicitly_allowlisted(self):
        for path in active_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != "add_event_handler":
                    continue
                source = ast.unparse(node)
                if "incoming=True" in source:
                    self.assertIn(path.relative_to(ROOT), ALLOWED_DIRECT_EVENTS)

    def test_media_and_ai_transcription_use_shared_media_download_boundary(self):
        targets = [
            ROOT / "plugins/security/ephemeral.py",
            ROOT / "plugins/media/ocr.py",
            ROOT / "plugins/ai_gateway/transcribe.py",
        ]
        for path in targets:
            text = path.read_text(encoding="utf-8")
            self.assertIn("download_telegram_media", text, path.name)
            self.assertNotIn("event.client.download_media(media, file=", text, path.name)
            self.assertNotIn("event.client.download_media(reply.media, file=", text, path.name)

    def test_doctor_network_dns_is_off_event_loop(self):
        text = (ROOT / "plugins/system_ops/doctor.py").read_text(encoding="utf-8")
        self.assertIn("await asyncio.to_thread(socket.gethostbyname, host)", text)

    def test_identity_uses_unique_photo_snapshots_and_failure_safe_restore(self):
        text = (ROOT / "plugins/stealth/identity.py").read_text(encoding="utf-8")
        self.assertIn("uuid.uuid4().hex", text)
        self.assertIn("Upload first so a failed upload cannot destroy the current profile photo.", text)
        self.assertIn("Saved profile photo is outside the managed identity cache.", text)

    def test_plugin_behavior_audit_exists_and_is_ast_only(self):
        text = (ROOT / "tools/plugin_behavior_audit.py").read_text(encoding="utf-8")
        self.assertIn("ast.parse", text)
        self.assertNotIn("importlib.import_module", text)
        self.assertNotIn("exec(", text)


class Phase9MigrationGate(unittest.TestCase):
    def _source(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_system_plugins_use_shared_subprocess_boundary(self):
        for path in (
            "plugins/system/sysinfo.py",
            "plugins/backup/cloud_backup.py",
            "plugins/system_ops/doctor.py",
        ):
            source = self._source(path)
            self.assertIn('context.get("subprocess")', source, path)
            self.assertNotIn("helpers.shell", source, path)

    def test_ocr_uses_media_isolation_boundary(self):
        source = self._source("plugins/media/ocr.py")
        self.assertIn('context.get("media")', source)
        self.assertIn("run_isolated", source)
        self.assertNotIn("helpers.shell", source)


if __name__ == "__main__":
    unittest.main()
