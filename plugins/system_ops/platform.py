from __future__ import annotations

import json
import re
import time
from dataclasses import asdict

from core.context import get_application_context
from core.errors import CommandError
from core.registry import COMMANDS, list_registrations, register_cmd
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}(health|plugins|tasks|jobs|cache|stats|diagnostics|search|reindex|flags)(?:\s+(.*))?$"

_PLUGIN_STATES = frozenset({
    "DISCOVERED",
    "LOADED",
    "RUNNING",
    "FAILED_IMPORT",
    "FAILED_SETUP",
    "DISABLED",
    "UNLOADED",
})


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


def _plugin_manager(event):
    manager = getattr(event.client, "plugin_manager", None)
    if manager is None:
        raise CommandError("Plugin manager is unavailable")
    return manager


def _plugin_command_map():
    counts: dict[str, int] = {}
    for registration in list_registrations():
        owner = registration.owner
        if owner:
            counts[owner] = counts.get(owner, 0) + 1
    return counts


def _plugin_short_name(name: str) -> str:
    return name.removeprefix("plugins.")


def _find_plugin(records, query: str):
    needle = query.strip().lower()
    exact = [
        item for item in records
        if item["name"].lower() == needle
        or _plugin_short_name(item["name"]).lower() == needle
    ]
    if exact:
        return exact[0]
    matches = [
        item for item in records
        if needle and needle in item["name"].lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(_plugin_short_name(item["name"]) for item in matches[:8])
        raise CommandError(f"Plugin query is ambiguous: {names}")
    raise CommandError(f"Unknown plugin: {query}")


def _pack(items: list[str], width: int = 3, limit: int = 80) -> list[str]:
    rows: list[str] = []
    for index in range(0, min(len(items), limit), width):
        rows.append("  ·  ".join(items[index:index + width]))
    if len(items) > limit:
        rows.append(f"… +{len(items) - limit} more")
    return rows


def _plugin_overview(records, command_counts: dict[str, int]) -> list[str]:
    counts: dict[str, int] = {}
    for item in records:
        state = item["state"]
        counts[state] = counts.get(state, 0) + 1

    rows = [
        f"Plugins: {len(records)}  ·  Commands: {sum(command_counts.values())}",
        "  ·  ".join(
            f"{state}: {counts[state]}"
            for state in ("RUNNING", "LOADED", "DISABLED", "FAILED_IMPORT", "FAILED_SETUP", "UNLOADED", "DISCOVERED")
            if counts.get(state)
        ) or "No lifecycle state recorded.",
    ]

    attention = [
        f"{_plugin_short_name(item['name'])} → {item['state']}"
        for item in records
        if item["state"] not in {"RUNNING", "LOADED"}
    ]
    if attention:
        rows += ["", "ATTENTION"] + attention[:16]
        if len(attention) > 16:
            rows.append(f"… +{len(attention) - 16} more")

    running = [
        _plugin_short_name(item["name"])
        for item in records
        if item["state"] == "RUNNING"
    ]
    if running:
        rows += ["", "RUNNING"] + _pack(running)
    return rows


def _plugin_detail(record, command_counts: dict[str, int]) -> list[str]:
    name = record["name"]
    dependencies = record.get("dependencies") or []
    registrations = int(command_counts.get(name, 0))
    rows = [
        f"Plugin: {_plugin_short_name(name)}",
        f"State: {record['state']}",
        f"Commands: {registrations}",
        f"Critical: {'YES' if record.get('critical') else 'NO'}",
        f"Dependencies: {', '.join(_plugin_short_name(dep) for dep in dependencies) if dependencies else 'none'}",
    ]
    if record.get("error"):
        error = str(record["error"]).replace("\n", " ")
        rows.append(f"Error: {error[:300]}")
    if registrations:
        owned = [
            registration
            for registration in list_registrations()
            if registration.owner == name
        ]
        names = []
        for registration in owned[:20]:
            command_names = registration.pattern
            names.append(command_names)
        rows += ["", "REGISTRATIONS"] + _pack(names, width=1, limit=20)
        if len(owned) > 20:
            rows.append(f"… +{len(owned) - 20} more")
    return rows


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
        manager = _plugin_manager(event)
        records = manager.snapshot()
        command_counts = _plugin_command_map()
        if not arg:
            rows = _plugin_overview(records, command_counts)
            await event.edit(render("PLUGIN OBSERVATORY", rows or ["No plugins discovered."], footer="system_ops | plugins | live registry")); return

        parts = arg.split(maxsplit=1)
        selector = parts[0].lower()
        if selector in _PLUGIN_STATES:
            filtered = [item for item in records if item["state"] == selector]
            rows = [
                f"{_plugin_short_name(item['name'])}  ·  {command_counts.get(item['name'], 0)} cmd"
                for item in filtered
            ]
            rows = [f"State: {selector}", f"Count: {len(filtered)}", ""] + _pack(rows, width=1, limit=60)
            await event.edit(render("PLUGIN OBSERVATORY // FILTER", rows, footer=f"system_ops | plugins {selector.lower()}")); return

        record = _find_plugin(records, arg)
        rows = _plugin_detail(record, command_counts)
        await event.edit(render("PLUGIN OBSERVATORY // DETAIL", rows, footer=f"system_ops | plugins | {record['state']}")); return

    if cmd == "tasks":
        records = ctx.tasks.snapshot(); rows = [f"{r['state']} · {r['name']} · {r['owner'] or 'unknown'}" for r in records[-20:]]
        await event.edit(render("TASKS // SUPERVISOR", rows or ["No supervised tasks recorded."], footer="system_ops | tasks")); return

    if cmd == "jobs":
        jobs = await ctx.get("jobs").list(limit=20)
        rows = [f"{_state_name(job)} · {job.type} · {job.id[:12]} · {job.progress:.0%}" for job in jobs]
        await event.edit(render("JOBS // DURABLE", rows or ["No durable jobs recorded."], footer="system_ops | jobs")); return

    if cmd == "cache":
        stats = await ctx.get("cache").stats(); rows = [f"{key}: {value}" for key, value in sorted(asdict(stats).items())]
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
        report = {"timestamp": time.time(), "context": ctx.snapshot(), "plugins": plugin_manager.snapshot() if plugin_manager else [], "commands": len(COMMANDS), "tasks": ctx.tasks.snapshot(), "jobs": {"count": len(jobs), "states": states}, "cache": asdict(await ctx.get("cache").stats()), "db_integrity": await ctx.get("storage").integrity_check(), "metrics": asdict(metrics), "isolation": asdict(ctx.get("isolation").assess()), "search_ready": getattr(search, "_ready", False)}
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
