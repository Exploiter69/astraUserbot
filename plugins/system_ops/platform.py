from __future__ import annotations

import json
import re
import time
from dataclasses import asdict

from core.context import get_application_context
from core.errors import CommandError
from core.registry import COMMANDS, register_cmd
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(health|plugins|tasks|jobs|cache|stats|diagnostics|search|reindex|flags)(?:\s+(.*))?$"

def _redact(text: str) -> str:
    return re.sub(r"(?i)(api[_-]?hash|api[_-]?id|token|secret|password|authorization|session|cookie)[^\n:=]*[:=]\s*[^\n]+", "[REDACTED]", text)

def _ctx():
    ctx = get_application_context()
    if ctx is None:
        raise CommandError("Runtime context is unavailable")
    return ctx

def _state_name(job) -> str:
    state = getattr(job, "state", "")
    return getattr(state, "value", str(state))

async def setup(client):
    register_cmd(client, PATTERN, handle, "system_ops", "Astra platform health, diagnostics, search and feature controls.")

async def handle(event):
    cmd = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip()
    ctx = _ctx()

    if cmd == "health":
        storage = ctx.get("storage")
        integrity = await storage.integrity_check()
        rows = [
            f"Runtime: {ctx.snapshot()['state']}", f"Services: {len(ctx.services)}", f"Tasks active: {len(ctx.tasks.active())}",
            f"Database integrity: {'PASS' if integrity else 'FAIL'}", f"Commands: {len(COMMANDS)}",
            f"Jobs worker: {'running' if getattr(ctx.get('jobs'), '_started', False) else 'stopped'}",
            f"HTTP: {'ready' if getattr(ctx.get('http'), 'session', None) else 'stopped'}",
            f"Search: {'ready' if getattr(ctx.get('search'), '_ready', False) else 'stopped'}",
            f"Isolation: {ctx.get('isolation').assess().backend}",
        ]
        await event.edit(render("HEALTH // PLATFORM", rows, footer="system_ops | health")); return

    if cmd == "plugins":
        manager = getattr(event.client, "plugin_manager", None)
        if manager is None: raise CommandError("Plugin manager is unavailable")
        records = manager.snapshot(); counts: dict[str, int] = {}
        for item in records: counts[item["state"]] = counts.get(item["state"], 0) + 1
        rows = [f"{state}: {count}" for state, count in sorted(counts.items())]
        rows += [f"{item['name']} → {item['state']}" for item in records if item["state"] not in {"RUNNING", "LOADED"}][:12]
        await event.edit(render("PLUGINS // STATE", rows or ["No plugins discovered."], footer="system_ops | plugins")); return

    if cmd == "tasks":
        records = ctx.tasks.snapshot(); rows = [f"{r['state']} · {r['name']} · {r['owner'] or 'unknown'}" for r in records[-20:]]
        await event.edit(render("TASKS // SUPERVISOR", rows or ["No supervised tasks recorded."], footer="system_ops | tasks")); return

    if cmd == "jobs":
        jobs = await ctx.get("jobs").list(limit=20)
        rows = [f"{_state_name(job)} · {job.type} · {job.id[:12]} · {job.progress:.0%}" for job in jobs]
        await event.edit(render("JOBS // DURABLE", rows or ["No durable jobs recorded."], footer="system_ops | jobs")); return

    if cmd == "cache":
        stats = ctx.get("cache").stats(); rows = [f"{key}: {value}" for key, value in sorted(stats.items())]
        await event.edit(render("CACHE // STATE", rows[:20] or ["No cache statistics available."], footer="system_ops | cache")); return

    if cmd == "stats":
        snapshot = ctx.get("metrics").snapshot()
        rows = [f"{name}: {value}" for name, value in sorted(snapshot.counters.items())]
        rows += [f"{name}: avg {value['avg_ms']:.1f}ms p95 {value['p95_ms']:.1f}ms n={int(value['count'])}" for name, value in sorted(snapshot.timings.items())]
        resource = snapshot.resources
        rows += [f"RSS: {resource['rss_bytes'] / 1024 / 1024:.1f} MiB", f"Disk free: {resource['disk_free_bytes'] / 1024 / 1024 / 1024:.1f} GiB"]
        try:
            jobs = await ctx.get("jobs").list(limit=100)
        except Exception as exc:
            raise CommandError("Unable to read durable job statistics.") from exc
        queued = sum(1 for job in jobs if _state_name(job) == "QUEUED")
        uncertain = sum(1 for job in jobs if _state_name(job) == "UNCERTAIN")
        rows += [f"Jobs sampled: {len(jobs)}", f"Queued: {queued}", f"Uncertain: {uncertain}"]
        await event.edit(render("STATS // PERFORMANCE", rows[:30], footer="system_ops | stats")); return

    if cmd == "diagnostics":
        plugin_manager = getattr(event.client, "plugin_manager", None)
        jobs = await ctx.get("jobs").list(limit=100); search = ctx.get("search"); metrics = ctx.get("metrics").snapshot()
        states = {}
        for job in jobs: states[_state_name(job)] = states.get(_state_name(job), 0) + 1
        report = {"timestamp": time.time(), "context": ctx.snapshot(), "plugins": plugin_manager.snapshot() if plugin_manager else [], "commands": len(COMMANDS), "tasks": ctx.tasks.snapshot(), "jobs": {"count": len(jobs), "states": states}, "cache": ctx.get("cache").stats(), "db_integrity": await ctx.get("storage").integrity_check(), "metrics": asdict(metrics), "isolation": asdict(ctx.get("isolation").assess()), "search_ready": getattr(search, "_ready", False)}
        path = ctx.project_root / "data" / "logs" / f"diagnostics_{int(time.time())}.json"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_redact(json.dumps(report, indent=2, default=str))[:200_000], encoding="utf-8")
        await event.edit(render("DIAGNOSTICS // REPORT", [f"Written: {path.relative_to(ctx.project_root)}", f"DB integrity: {'PASS' if report['db_integrity'] else 'FAIL'}", f"Plugins: {len(report['plugins'])}", f"Commands: {report['commands']}", f"Jobs sampled: {len(jobs)}"], footer="system_ops | diagnostics")); return

    if cmd == "search":
        if not arg: raise CommandError(f"Usage: {config.PREFIX}search <query>")
        if len(arg) > 512: raise CommandError("Search query must be 512 characters or fewer.")
        results = await ctx.get("search").search(arg, limit=10)
        rows = [f"[{item.source}] {item.title}: {item.snippet}" for item in results]
        await event.edit(render("SEARCH // RESULTS", rows or ["No results."], footer=f"system_ops | search | {len(results)}")); return

    if cmd == "reindex":
        counts = await ctx.get("search").rebuild(); rows = [f"{source}: {count}" for source, count in sorted(counts.items())]
        await event.edit(render("SEARCH // REBUILT", rows, footer="system_ops | reindex")); return

    if cmd == "flags":
        parts = arg.split(); flags = ctx.get("flags")
        if not parts:
            items = await flags.list(); rows = [f"{item['name']}: {'ON' if item['enabled'] else 'OFF'}" for item in items]
            await event.edit(render("FLAGS // STATE", rows or ["No feature flags."], footer="system_ops | flags")); return
        if len(parts) != 2 or parts[1].lower() not in {"on", "off"}: raise CommandError(f"Usage: {config.PREFIX}flags <name> <on|off>")
        await flags.set(parts[0], parts[1].lower() == "on", {"operator": "owner"})
        await event.edit(render("FLAGS // UPDATED", [f"{parts[0]}: {'ON' if parts[1].lower() == 'on' else 'OFF'}"], footer="system_ops | flags"))
