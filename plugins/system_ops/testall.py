from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from core.registry import register_cmd, COMMANDS
from helpers.hud import render
from helpers.net import get_session
from helpers.shell import run
from config import config

logger = logging.getLogger("astra.testall")
PATTERN = rf"^{re.escape(config.PREFIX)}testall(?:\s+(safe|report|network|static))?$"

# Commands that are safe to exercise automatically. Everything else is inspected,
# parsed and dependency-checked but not executed because it may mutate Telegram,
# the filesystem, a cloud remote, a database, or the host.
SAFE_COMMANDS = {
    "ping",
    "sysinfo",
    "help",
    "doctor",
    "speedtest",
    "dns",
    "headers",
    "ip",
    "hash",
    "passgen",
}

BINARY_BY_COMMAND = {
    "ff": ["ffmpeg", "ffprobe"],
    "mediaflow": ["ffmpeg"],
    "round": ["ffmpeg"],
    "compress": ["ffmpeg"],
    "reverse": ["ffmpeg"],
    "ss": ["ffmpeg"],
    "ocr": ["tesseract"],
    "rclone": ["rclone"],
    "aria": ["aria2c"],
    "rip": ["yt-dlp"],
    "update": ["git", "systemctl"],
}


def _command_names(pattern: str) -> list[str]:
    raw = pattern.replace(f"^{re.escape(config.PREFIX)}", "")
    raw = raw.split("(?")[0].replace("$", "").replace("\\", "")
    if raw.startswith("(") and raw.endswith(")"):
        return [x for x in raw.strip("()").split("|") if x]
    match = re.search(r"\(([^)]+)\)", pattern)
    if match:
        return [x for x in match.group(1).split("|") if not x.startswith("?") and x]
    return [raw] if raw else []



def _all_commands() -> list[str]:
    names: set[str] = set()
    for pattern in COMMANDS:
        names.update(_command_names(pattern))
    return sorted(names)


def _classify(name: str) -> str:
    if name in SAFE_COMMANDS:
        return "SAFE-SMOKE"
    if name in {"purge", "purgeme", "zombies", "promote", "demote", "slow", "kickme", "block", "unblock", "clone", "revert", "savevo", "arch", "track", "pmpermit", "disallow", "disapprove", "backup", "autopost", "update", "cleancache", "vault", "savenote", "delnote_sec", "logger", "mirror", "setlogger", "read"}:
        return "MUTATING-SKIP"
    return "DEPENDENCY-SMOKE"


def _safe_text(value: str, limit: int = 800) -> str:
    value = re.sub(r"(?i)(api[_-]?hash|api[_-]?id|token|secret|password|authorization|session)[^\n:=]*[:=]\s*[^\n]+", "[REDACTED]", value)
    return value[-limit:]


def _write_report(report: dict) -> Path:
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = log_dir / f"testall_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


async def _network_probe(client) -> tuple[bool, str]:
    started = time.perf_counter()
    try:
        if not client.is_connected():
            await client.connect()
        me = await client.get_me()
        elapsed = (time.perf_counter() - started) * 1000
        if me is None:
            return False, f"Telegram connected but identity lookup returned empty ({elapsed:.0f} ms)"
        label = getattr(me, "username", None) or getattr(me, "first_name", None) or "authorized user"
        return True, f"Telegram MTProto OK · {label} · {elapsed:.0f} ms"
    except Exception as exc:
        return False, f"Telegram probe failed: {type(exc).__name__}: {_safe_text(str(exc), 240)}"


async def _dependency_probe() -> list[dict]:
    results = []
    seen: set[str] = set()
    for command in _all_commands():
        for binary in BINARY_BY_COMMAND.get(command, []):
            if binary in seen:
                continue
            seen.add(binary)
            results.append({"command": command, "binary": binary, "ok": bool(shutil.which(binary))})
    return results


async def _static_probe() -> list[dict]:
    results = []
    project_root = Path(__file__).resolve().parents[2]
    for path in sorted((project_root / "plugins").rglob("*.py")):
        if path.name == "__init__.py":
            continue
        item = {"plugin": str(path.relative_to(project_root)), "ok": True}
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except Exception as exc:
            item.update(ok=False, error=f"{type(exc).__name__}: {_safe_text(str(exc))}")
        results.append(item)
    return results


class _PatternMatch:
    def __init__(self, groups: tuple[str | None, ...]):
        self._groups = groups

    def group(self, index: int = 0):
        if index == 0:
            return None
        return self._groups[index - 1] if index - 1 < len(self._groups) else None


class _SyntheticEvent:
    """In-process event used for non-mutating handler smoke tests.

    It never sends a Telegram message, deletes anything, or calls client APIs.
    Handlers that need a live Telegram event are excluded from this direct tier.
    """
    out = True
    is_reply = False
    reply_to_msg_id = None
    chat_id = 0
    id = 0

    def __init__(self, groups: tuple[str | None, ...]):
        self.pattern_match = _PatternMatch(groups)
        self.client = None
        self.output = ""

    async def edit(self, text):
        self.output = str(text)
        return self

    async def respond(self, *args, **kwargs):
        self.output = str(args[0]) if args else ""
        return self

    async def delete(self):
        return None


DIRECT_CASES = {
    "ping": (),
    "sysinfo": (),
    "help": (None,),
    "dns": ("example.com", "A"),
    "headers": ("https://example.com",),
    "ip": ("1.1.1.1",),
    "hash": ("astra-test",),
    "passgen": ("12",),
}


async def _safe_smoke(client) -> list[dict]:
    results = []
    for pattern, meta in COMMANDS.items():
        names = _command_names(pattern)
        for name in names:
            if name not in DIRECT_CASES:
                continue
            handler_name = meta.get("handler", "")
            handler = None
            module_name = None
            for module in list(sys.modules.values()):
                if module is None:
                    continue
                candidate = getattr(module, handler_name, None)
                if candidate is not None and inspect.iscoroutinefunction(candidate):
                    handler = candidate
                    module_name = getattr(module, "__name__", "?")
                    break
            if handler is None:
                results.append({"command": name, "ok": False, "phase": "direct", "error": "async handler not found"})
                continue
            fake = _SyntheticEvent(DIRECT_CASES[name])
            started = time.perf_counter()
            try:
                await asyncio.wait_for(handler(fake), timeout=12)
                results.append({
                    "command": name,
                    "ok": True,
                    "phase": "direct",
                    "module": module_name,
                    "handler": handler_name,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "output_bytes": len(fake.output.encode("utf-8")),
                })
            except Exception as exc:
                results.append({
                    "command": name,
                    "ok": False,
                    "phase": "direct",
                    "module": module_name,
                    "handler": handler_name,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": f"{type(exc).__name__}: {_safe_text(str(exc), 500)}",
                })
    return results


async def _run_testall(event, mode: str) -> None:
    started = time.perf_counter()
    await event.edit(render("TESTALL // START", [
        "Running non-destructive self-test suite...",
        "No destructive Telegram/system commands will be executed.",
        "Building plugin, registry, dependency and network checks...",
    ], footer="system_ops | testall"))

    static = [] if mode == "network" else await _static_probe()
    deps = [] if mode == "static" else await _dependency_probe()
    safe = [] if mode in {"network", "static"} else await _safe_smoke(event.client)
    network_ok = None
    network_message = "not requested"
    if mode in {"safe", "report", "network"}:
        network_ok, network_message = await _network_probe(event.client)

    commands = _all_commands()
    counts = {
        "commands": len(commands),
        "registry": len(COMMANDS),
        "static_ok": sum(1 for x in static if x["ok"]),
        "static_total": len(static),
        "deps_ok": sum(1 for x in deps if x["ok"]),
        "deps_total": len(deps),
        "safe_ok": sum(1 for x in safe if x["ok"]),
        "safe_total": len(safe),
        "mutating_skipped": sum(1 for x in commands if _classify(x) == "MUTATING-SKIP"),
    }

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "counts": counts,
        "network": {"ok": network_ok, "message": network_message},
        "static": static,
        "dependencies": deps,
        "safe_smoke": safe,
        "command_classification": {name: _classify(name) for name in commands},
    }
    report_path = _write_report(report)

    failed_static = counts["static_total"] - counts["static_ok"]
    missing_deps = counts["deps_total"] - counts["deps_ok"]
    failed_safe = counts["safe_total"] - counts["safe_ok"]
    overall = failed_static == 0 and failed_safe == 0 and (network_ok is not False)

    rows = [
        f"Overall: {'HEALTHY ✓' if overall else 'ATTENTION REQUIRED ⚠'}",
        f"Registry: {counts['registry']} patterns / {counts['commands']} commands",
        f"Python syntax: {counts['static_ok']}/{counts['static_total']} clean" if static else "Python syntax: skipped",
        f"Dependencies: {counts['deps_ok']}/{counts['deps_total']} available" if deps else "Dependencies: skipped",
        f"Safe smoke: {counts['safe_ok']}/{counts['safe_total']} callable" if safe else "Safe smoke: skipped",
        f"Telegram: {'OK ✓' if network_ok else 'FAIL ✗' if network_ok is False else 'skipped'}",
        f"Mutating commands skipped: {counts['mutating_skipped']}",
        f"Report: {report_path}",
    ]
    if missing_deps:
        rows.append(f"Missing binaries: {missing_deps}")
    if failed_static:
        rows.append(f"Syntax failures: {failed_static}")
    if failed_safe:
        rows.append(f"Safe registration failures: {failed_safe}")

    await event.edit(render("TESTALL // REPORT", rows, footer=f"{time.perf_counter() - started:.2f}s | {mode}"))


async def setup(client):
    register_cmd(client, PATTERN, handle_testall, "system_ops", "Non-destructive Astra-wide plugin, dependency and Telegram health test suite.")


async def handle_testall(event):
    mode = (event.pattern_match.group(1) or "report").lower()
    await _run_testall(event, mode)
