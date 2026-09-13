"""Read-only isolation/security audit plus a real Bubblewrap execution probe."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from core.errors import TimeoutError
from core.services.isolation import IsolationService
from helpers.archive import ArchiveSafetyError, extract_archive

ROOT = Path(__file__).resolve().parents[1]


def source_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


async def isolated_probe(service: IsolationService) -> dict[str, bool]:
    if not service.assess().enabled:
        raise RuntimeError("Bubblewrap is required for the isolation security gate")

    with tempfile.TemporaryDirectory(prefix="astra-isolation-audit-") as tmp:
        root = Path(tmp)
        host_secret = root.parent / "host-secret.txt"
        host_secret.write_text("DO_NOT_EXPOSE", encoding="utf-8")
        try:
            code = (
                "import os,socket\n"
                "print('ENV=' + os.environ.get('ASTRA_API_HASH','MISSING'))\n"
                "print('HOST=' + ('VISIBLE' if os.path.exists('/workspace/../host-secret.txt') else 'HIDDEN'))\n"
                "print('HOME=' + ('VISIBLE' if os.path.exists('/home') else 'HIDDEN'))\n"
                "try:\n"
                "    socket.create_connection(('1.1.1.1',80),0.2)\n"
                "except OSError:\n"
                "    print('NET=BLOCKED')\n"
                "else:\n"
                "    print('NET=OPEN')\n"
            )
            result = await service.run(
                ["python3", "-c", code],
                workspace=root,
                timeout=5,
                max_output_bytes=16 * 1024,
            )
            stdout = result.stdout
            timeout_ok = False
            try:
                await service.run(
                    ["python3", "-c", "while True: pass"],
                    workspace=root,
                    timeout=0.5,
                    max_output_bytes=1024,
                )
            except TimeoutError:
                timeout_ok = True
            return {
                "actual_isolated_execution": result.returncode == 0,
                "filesystem_boundary": "HOST=HIDDEN" in stdout and "HOME=HIDDEN" in stdout,
                "network_isolation": "NET=BLOCKED" in stdout,
                "environment_allowlist": "ENV=MISSING" in stdout,
                "subprocess_timeout": timeout_ok,
            }
        finally:
            host_secret.unlink(missing_ok=True)


def archive_probe() -> bool:
    import tarfile
    import zipfile

    with tempfile.TemporaryDirectory(prefix="astra-archive-audit-") as tmp:
        root = Path(tmp)
        destination = root / "out"
        zip_path = root / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../escape.txt", "blocked")
        try:
            extract_archive(zip_path, destination)
        except ArchiveSafetyError:
            pass
        else:
            return False

        tar_path = root / "link.tar"
        with tarfile.open(tar_path, "w") as tf:
            info = tarfile.TarInfo("escape")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        try:
            extract_archive(tar_path, destination)
        except ArchiveSafetyError:
            pass
        else:
            return False

        safe = root / "safe.zip"
        with zipfile.ZipFile(safe, "w") as zf:
            zf.writestr("nested/file.txt", "safe")
        return extract_archive(safe, destination) == 1 and (destination / "nested/file.txt").read_text() == "safe"


def static_checks() -> dict[str, bool]:
    isolation = source_text("core/services/isolation.py")
    subprocess = source_text("core/services/subprocess.py")
    workspace = source_text("core/services/workspace.py")
    media = source_text("core/services/media.py")
    eval_source = source_text("plugins/system/eval.py")
    ocr = source_text("plugins/media/ocr.py")
    archive = source_text("helpers/archive.py")

    python_files = [p for p in ROOT.rglob("*.py") if ".git" not in p.parts and ".venv" not in p.parts]
    combined = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in python_files)

    return {
        "bubblewrap_executor": "--unshare-all" in isolation and "--clearenv" in isolation and "--bind" in isolation,
        "network_policy": "--unshare-all" in isolation,
        "environment_policy": "--clearenv" in isolation and '"PATH":' in isolation and '"HOME": "/tmp"' in isolation,
        "resource_limits": all(token in isolation for token in ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_NPROC", "RLIMIT_NOFILE")),
        "argv_only_subprocess": "create_subprocess_exec" in subprocess and "shell=True" not in combined and "os.system(" not in combined,
        "workspace_path_boundary": "relative_to(self.root)" in workspace and "Cannot remove workspace root" in workspace,
        "archive_traversal": "Archive member escapes extraction root" in archive and "Archive links and special files are not allowed" in archive,
        "eval_isolated": 'context.get("isolation")' in eval_source and "isolation.run(" in eval_source and '"-I"' in eval_source,
        "media_decoder_isolated": "run_isolated(" in media and "self.isolation.run(" in media,
        "ocr_isolated": "run_isolated(" in ocr,
        "secret_safe_logging": "process_env" in subprocess and "logger.debug" in subprocess and "stdout" not in subprocess.split("logger.debug", 1)[1].split("\n", 1)[0],
    }


async def main() -> int:
    print("=== ISOLATION / SECURITY HARDENING AUDIT ===")
    checks = static_checks()
    for key, value in checks.items():
        print(f"{key}: {'PASS' if value else 'FAIL'}")

    service = IsolationService()
    await service.start()
    live = await isolated_probe(service)
    for key, value in live.items():
        print(f"{key}: {'PASS' if value else 'FAIL'}")

    archive_ok = archive_probe()
    print(f"archive_safety_probe: {'PASS' if archive_ok else 'FAIL'}")

    all_checks = {**checks, **live, "archive_safety_probe": archive_ok}
    if all(all_checks.values()):
        print("ISOLATION_SECURITY_HARDENING_AUDIT_PASS")
        return 0
    print("ISOLATION_SECURITY_HARDENING_AUDIT_FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
