import asyncio
import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.services.isolation import IsolationService, IsolationUnavailable
from helpers.archive import ArchiveSafetyError, extract_archive


class IsolationSecurityTests(unittest.TestCase):
    def test_environment_is_fixed_allowlist(self):
        env = IsolationService._minimal_environment()
        self.assertEqual(set(env), {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"})
        self.assertNotIn("ASTRA_API_HASH", env)
        self.assertNotIn("API_HASH", env)
        self.assertEqual(env["HOME"], "/tmp")

    def test_backend_is_explicit(self):
        service = IsolationService()
        with self.assertRaises(IsolationUnavailable):
            service.require_explicit_backend()

    def test_zip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "evil.zip"
            destination = Path(tmp) / "out"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escape.txt", "owned")
            with self.assertRaises(ArchiveSafetyError):
                extract_archive(archive, destination)
            self.assertFalse((Path(tmp).parent / "escape.txt").exists())

    def test_tar_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "evil.tar"
            destination = Path(tmp) / "out"
            with tarfile.open(archive, "w") as tf:
                info = tarfile.TarInfo("escape")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tf.addfile(info)
            with self.assertRaises(ArchiveSafetyError):
                extract_archive(archive, destination)

    def test_archive_limits_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "many.zip"
            destination = Path(tmp) / "out"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("a", "1")
                zf.writestr("b", "2")
            with self.assertRaises(ArchiveSafetyError):
                extract_archive(archive, destination, max_entries=1)

    def test_safe_zip_extracts_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "safe.zip"
            destination = Path(tmp) / "out"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("nested/file.txt", "safe")
            self.assertEqual(extract_archive(archive, destination), 1)
            self.assertEqual((destination / "nested/file.txt").read_text(), "safe")

    def test_safe_tar_extracts_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "safe.tar"
            destination = Path(tmp) / "out"
            payload = b"safe"
            with tarfile.open(archive, "w") as tf:
                info = tarfile.TarInfo("nested/file.txt")
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            self.assertEqual(extract_archive(archive, destination), 1)
            self.assertEqual((destination / "nested/file.txt").read_text(), "safe")

    def test_actual_bubblewrap_execution_when_available(self):
        async def run():
            service = IsolationService()
            await service.start()
            if not service.assess().enabled:
                return None
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result = await service.run(
                    ["python3", "-c", "import os; print(os.environ.get('ASTRA_API_HASH', 'MISSING')); print(os.path.exists('/home')); print(os.path.exists('/workspace'))"],
                    workspace=root,
                    timeout=10,
                )
                return result

        result = asyncio.run(run())
        if result is None:
            self.skipTest("Bubblewrap is unavailable on this host")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MISSING", result.stdout)
        self.assertIn("False", result.stdout)
        self.assertIn("True", result.stdout)


if __name__ == "__main__":
    unittest.main()
