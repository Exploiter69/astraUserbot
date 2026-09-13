from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import re

from core.context import get_application_context
from core.registry import register_cmd, COMMANDS
from core.errors import CommandError
from helpers.hud import render
from config import config

logger = logging.getLogger("astra.doctor")
PATTERN = rf"^{re.escape(config.PREFIX)}(doctor|cleancache|update)$"
_REPORT_RETENTION_COUNT = 50
_REPORT_RETENTION_BYTES = 20 * 1024 * 1024


def _redact(text: str) -> str:
    return re.sub(r"(?i)(api[_-]?hash|api[_-]?id|token|secret|password|authorization|session)[^\n:=]*[:=]\s*[^\n]+", "[REDACTED]", text)


def _report_path(prefix: str = "doctor") -> Path:
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return log_dir / f"{prefix}_{stamp}.json"


def _trim_reports(log_dir: Path) -> None:
    reports = sorted(log_dir.glob("doctor_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    total = 0
    for index, path in enumerate(reports):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if index >= _REPORT_RETENTION_COUNT or total + size > _REPORT_RETENTION_BYTES:
            try:
                path.unlink()
            except OSError:
                logger.warning("Could not remove old doctor report %s", path, exc_info=True)
            continue
        total += size


async def _cmd(command: list[str], timeout: int = 5) -> tuple[bool, str]:
    context = get_application_context()
    if context is None:
        return False, "Subprocess service unavailable"
    subprocess = context.get("subprocess")
    try:
        result = await subprocess.run(command, timeout=timeout, max_output_bytes=64 * 1024)
        text = (result.stdout.strip() or result.stderr.strip()).strip()
        return result.returncode == 0, _redact(text[-1000:])
    except Exception as exc:
        return False, f"{type(exc).__name__}: {_redact(str(exc))}"


async def _network_checks(client) -> list[dict]:
    checks = []
    started = time.perf_counter()
    try:
        if not client.is_connected():
            await client.connect()
        me = await client.get_me()
        checks.append({"name": "Telegram MTProto", "ok": me is not None, "detail": "connected + identity lookup"})
    except Exception as exc:
        checks.append({"name": "Telegram MTProto", "ok": False, "detail": f"{type(exc).__name__}: {_redact(str(exc))}"})

    for host in ("api.telegram.org", "1.1.1.1"):
        try:
            await asyncio.to_thread(socket.gethostbyname, host)
            checks.append({"name": f"DNS {host}", "ok": True, "detail": "resolved"})
        except Exception as exc:
            checks.append({"name": f"DNS {host}", "ok": False, "detail": type(exc).__name__})

    context = get_application_context()
    try:
        if context is None:
            raise RuntimeError("HTTP service unavailable")
        http = context.get("http")
        response = await http.get("https://www.google.com/generate_204", timeout=5, response_limit=1024)
        checks.append({"name": "HTTPS", "ok": response.status < 500, "detail": f"HTTP {response.status}"})
    except Exception as exc:
        checks.append({"name": "HTTPS", "ok": False, "detail": f"{type(exc).__name__}: {_redact(str(exc))}"})

    checks.append({"name": "Network probe time", "ok": True, "detail": f"{time.perf_counter() - started:.2f}s"})
    return checks


async def _doctor_report(event) -> dict:
    root = Path(__file__).resolve().parents[2]
    cache = root / "data" / "cache"
    logs = root / "data" / "logs"
    data = root / "data"
    cache.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "healthy",
        "python": {"version": sys.version, "executable": sys.executable},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "paths": {"root": str(root), "data": str(data), "cache": str(cache), "logs": str(logs)},
        "registry": {"patterns": len(COMMANDS), "commands": sum(1 for _ in COMMANDS)},
        "filesystem": {},
        "binaries": {},
        "network": [],
    }

    for name, path in (("root", root), ("data", data), ("cache", cache), ("logs", logs)):
        report["filesystem"][name] = {"exists": path.exists(), "writable": os.access(path, os.W_OK)}

    for binary in ("git", "ffmpeg", "ffprobe", "tesseract", "rclone", "aria2c", "yt-dlp", "systemctl"):
        report["binaries"][binary] = shutil.which(binary) is not None

    ok_uname, uname = await _cmd(["uname", "-a"])
    ok_uptime, uptime = await _cmd(["uptime", "-p"])
    ok_mem, memory = await _cmd(["free", "-m"])
    ok_disk, disk = await _cmd(["df", "-h", str(root)])
    report["host"] = {"uname": uname if ok_uname else None, "uptime": uptime if ok_uptime else None, "memory": memory if ok_mem else None, "disk": disk if ok_disk else None}
    report["network"] = await _network_checks(event.client)
    report["session"] = {"configured": bool(config.SESSION_NAME), "path_exists": (root / "data" / config.SESSION_NAME).exists()}
    report["cache"] = {"files": sum(1 for p in cache.iterdir() if p.is_file())}
    log_files = [p for p in logs.iterdir() if p.is_file()]
    report["logs"] = {"files": len(log_files), "total_bytes": sum(p.stat().st_size for p in log_files), "main_log": str(logs / "astra.log") if (logs / "astra.log").exists() else None}

    failures = []
    for group in (report["filesystem"], report["binaries"]):
        failures.extend(k for k, v in group.items() if (isinstance(v, dict) and not v.get("exists", v.get("writable", False))) or v is False)
    failures.extend(x["name"] for x in report["network"] if not x["ok"])
    report["failures"] = failures
    report["status"] = "healthy" if not failures else "attention"
    return report


async def setup(client):
    register_cmd(client, PATTERN, handle_doctor, "system_ops", "Detailed Astra health audit, cache maintenance, and updater.")


async def handle_doctor(event):
    cmd = event.pattern_match.group(1).lower()

    if cmd == "doctor":
        await event.edit(render("DOCTOR // SCANNING", [
            "Checking Telegram session...",
            "Checking DNS + HTTPS reachability...",
            "Checking Python, filesystem and host tools...",
            "Building persistent diagnostic report...",
        ], footer="system_ops | doctor"))
        started = time.perf_counter()
        report = await _doctor_report(event)
        path = _report_path("doctor")
        await asyncio.to_thread(path.write_text, json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
        await asyncio.to_thread(_trim_reports, path.parent)

        net_ok = sum(1 for x in report["network"] if x["ok"])
        net_total = len(report["network"])
        missing = [name for name, present in report["binaries"].items() if not present]
        rows = [
            f"Status: {'HEALTHY ✓' if report['status'] == 'healthy' else 'ATTENTION ⚠'}",
            f"Telegram/network: {net_ok}/{net_total} checks passed",
            f"Registry: {report['registry']['patterns']} registered patterns",
            f"Python: {platform.python_version()}",
            f"Platform: {platform.system()} {platform.release()} / {platform.machine()}",
            f"Session file: {'present ✓' if report['session']['path_exists'] else 'missing ⚠'}",
            f"Cache: {report['cache']['files']} files · Logs: {report['logs']['files']} files",
            f"Log size: {report['logs']['total_bytes'] / 1024:.1f} KiB",
            f"Diagnostic log: {path}",
        ]
        if missing:
            rows.append("Optional tools missing: " + ", ".join(missing))
        if report["failures"]:
            rows.append("Failed: " + ", ".join(report["failures"][:6]))
        await event.edit(render("DOCTOR // REPORT", rows, footer=f"{time.perf_counter() - started:.2f}s | system_ops"))
        return

    if cmd == "cleancache":
        cache_dir = Path("data/cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        entries = list(cache_dir.iterdir())
        count = 0
        for path in entries:
            try:
                if path.is_file() or path.is_symlink():
                    await asyncio.to_thread(path.unlink)
                elif path.is_dir():
                    await asyncio.to_thread(shutil.rmtree, path)
                count += 1
            except OSError as exc:
                logger.warning("Could not remove cache item %s: %s", path, exc)
        await event.edit(render("CACHE // CLEAN", [f"Purged {count} staging items.", "Persistent databases and Telegram session were left untouched."], footer="system_ops | cleancache"))
        return

    if cmd == "update":
        raise CommandError("Updater is intentionally disabled in this build. Update Astra from the project directory, review the diff, then restart the service.")
