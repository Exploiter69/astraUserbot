"""Post-Phase-10 product spine: search, inspect, correlation, plugin UX, AI UX and control plane."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from pathlib import Path

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import command_metadata, find_registrations, list_registrations, register_cmd
from helpers.hud import render
from helpers.ux import list_buttons, form_buttons, gallery_buttons


PRODUCT_PATTERN = rf"^{config.PREFIX}(inspect|correlate)(?:\s+(.*))?$"
PLUGIN_PATTERN = rf"^{config.PREFIX}plugin(?:\s+(search|enable|disable|reload|health|install))?(?:\s+(.*))?$"
AI_PATTERN = rf"^{config.PREFIX}aiux(?:\s+(summarize|explain|search|evidence|case|timeline|media))?(?:\s+(.*))?$"
CONTROL_PATTERN = rf"^{config.PREFIX}(doctor|config|update|restart)(?:\s+(.*))?$"


def _ctx():
    ctx = get_application_context()
    if ctx is None:
        raise CommandError("Runtime context is unavailable")
    return ctx


def _manager(event):
    manager = getattr(event.client, "plugin_manager", None)
    if manager is None:
        raise CommandError("Plugin manager is unavailable")
    return manager


def _plugin_name(name: str) -> str:
    return name.removeprefix("plugins.")


def _find_plugin(records, query: str):
    needle = query.strip().lower()
    exact = [r for r in records if r["name"].lower() == needle or _plugin_name(r["name"]).lower() == needle]
    if exact:
        return exact[0]
    matches = [r for r in records if needle and needle in r["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise CommandError("Ambiguous plugin: " + ", ".join(_plugin_name(r["name"]) for r in matches[:8]))
    raise CommandError(f"Unknown plugin: {query}")


async def setup(client):
    register_cmd(client, PRODUCT_PATTERN, handle_product, "product", "Unified entity inspection and evidence-backed correlation.", examples=[f"{config.PREFIX}inspect example.com", f"{config.PREFIX}correlate example.com"])
    register_cmd(client, PLUGIN_PATTERN, handle_plugin, "system_ops", "Plugin catalog, detail, compatibility and safe lifecycle controls.", operation_class="MUTATION", destructive=False, examples=[f"{config.PREFIX}plugin", f"{config.PREFIX}plugin search intel", f"{config.PREFIX}plugin health plugins.intelligence.security_intel"])
    register_cmd(client, AI_PATTERN, handle_aiux, "ai", "Native AI product flows over bounded replies, search, evidence, cases and media.", operation_class="NETWORK", network=True, examples=[f"{config.PREFIX}aiux summarize", f"{config.PREFIX}aiux search intel"])
    register_cmd(client, CONTROL_PATTERN, handle_control, "system_ops", "Operator doctor, safe config inspection, update preflight and controlled restart.", operation_class="MUTATION", examples=[f"{config.PREFIX}doctor", f"{config.PREFIX}update check", f"{config.PREFIX}restart confirm"])


async def handle_product(event):
    action = event.pattern_match.group(1).lower()
    target = (event.pattern_match.group(2) or "").strip()
    if not target:
        raise CommandError(f"Usage: {config.PREFIX}{action} <target>")
    if action == "inspect":
        rows = await inspect_target(target)
        await event.edit(render("ENTITY // INSPECTOR", rows[:36], footer="product | inspect | observed/derived/possible/unknown"))
        return
    rows = await correlate_target(target)
    await event.edit(render("INTELLIGENCE // CORRELATION", rows[:36], footer="product | correlate | evidence-backed"))


async def inspect_target(target: str) -> list[str]:
    ctx = _ctx()
    target = target[:512]
    rows = [f"Target: {target}", "---"]
    if target.startswith("case:"):
        case_id = target.split(":", 1)[1].strip()
        case = await ctx.get("cases").get(case_id)
        if not case:
            raise CommandError("Case not found.")
        rows += [f"Type: CASE", f"State: {case['status']}", f"Title: {case['title']}", f"Summary: {case['summary'] or '—'}"]
        rows.append("Evidence state: OBSERVED/DURABLE CASE RECORD")
        return rows

    if target.startswith("plugin:"):
        record = _find_plugin(getattr(_manager_stub(ctx), "snapshot")(), target.split(":", 1)[1])
        rows += [f"Type: PLUGIN", f"State: {record['state']}", f"Version: {record['version']}", f"API: {record['api_version']}", f"Description: {record['description'] or '—'}"]
        rows.append(f"Capabilities: {', '.join(record['capabilities']) or 'none'}")
        return rows

    if target.startswith("command:"):
        matches = find_registrations(target.split(":", 1)[1])
        if not matches:
            raise CommandError("Command not found.")
        meta = command_metadata(matches[0])
        rows += [f"Type: COMMAND", f"Category: {meta['category']}", f"Plugin: {meta['plugin'] or 'legacy'}", f"Permission: {meta['permission']}", f"Operation: {meta['operation_class']}", f"Usage: {meta['usage']}"]
        rows.append(f"Examples: {' | '.join(meta['examples'])}")
        return rows

    graph = ctx.get("intelgraph")
    matches = await graph.resolve_target(target)
    if not matches:
        rows.append("Observed fact: no matching IntelGraph entity.")
        rows.append("Unknown: no identity or relationship claim is made.")
        return rows
    if len(matches) > 1:
        rows.append("Observed fact: target is ambiguous.")
        rows.extend(f"Candidate: {item['entity_type']} · {item['display_value'] or item['canonical_value']}" for item in matches[:12])
        rows.append("Unknown: no identity claim selected.")
        return rows
    entity = matches[0]
    rows += [f"Type: {entity['entity_type']}", f"Canonical: {entity['canonical_value']}", f"Display: {entity.get('display_value') or '—'}", "Evidence state: OBSERVED ENTITY"]
    graph_result = await graph.graph(target, limit=12, offset=0)
    if graph_result:
        rows.append("---")
        rows.append(f"Relationships: {graph_result['total_edges']}")
        for edge in graph_result["edges"][:10]:
            other_id = edge["to_id"] if edge["from_id"] == entity["entity_id"] else edge["from_id"]
            other = next((node for node in graph_result["nodes"] if node["entity_id"] == other_id), None)
            if other:
                rows.append(f"{edge['relationship_type']} → {other['entity_type']} {other.get('display_value') or other['canonical_value']} · {edge['evidence_state']} · confidence={float(edge['confidence']):.2f}")
    observations = await ctx.get("storage").fetchall(
        "SELECT observation_id,source_id,evidence_state,confidence,COALESCE(observed_at,retrieved_at) FROM intel_observations WHERE entity_id=? ORDER BY COALESCE(observed_at,retrieved_at) DESC LIMIT 10",
        (entity["entity_id"],),
    )
    if observations:
        rows.append("---")
        rows.append("Evidence")
        rows.extend(f"{item[0][:12]} · source={item[1]} · {item[2]} · confidence={float(item[3]):.2f} · t={float(item[4]):.0f}" for item in observations)
    rows.append("Safety: relationships are evidence-linked; no unsupported identity assertion is generated.")
    return rows


async def correlate_target(target: str) -> list[str]:
    ctx = _ctx()
    result = await ctx.get("intelgraph").graph(target[:512], limit=25, offset=0)
    if result is None:
        return ["Unknown: no entity match."]
    if result.get("ambiguous"):
        return ["Possible correlation candidates:"] + [f"{item['entity_type']} · {item['canonical_value']}" for item in result["candidates"][:15]] + ["No candidate was selected."]
    rows = [f"Root: {result['root']['entity_type']} · {result['root'].get('display_value') or result['root']['canonical_value']}", f"Edges: {result['total_edges']}"]
    for edge in result["edges"][:20]:
        other_id = edge["to_id"] if edge["from_id"] == result["root"]["entity_id"] else edge["from_id"]
        other = next((node for node in result["nodes"] if node["entity_id"] == other_id), None)
        if not other:
            continue
        rows.append(f"{edge['relationship_type']} → {other['entity_type']} {other.get('display_value') or other['canonical_value']} · state={edge['evidence_state']} · confidence={float(edge['confidence']):.2f}")
    rows.append("Interpretation: observed facts and derived relationships remain explicitly separated.")
    return rows


def _manager_stub(ctx):
    return getattr(ctx, "plugin_manager", None)


async def handle_plugin(event):
    manager = _manager(event)
    action = (event.pattern_match.group(1) or "").lower()
    arg = (event.pattern_match.group(2) or "").strip()
    records = manager.snapshot()
    if not action:
        rows = [f"{_plugin_name(r['name'])} · {r['state']} · v{r['version']} · {len(r['capabilities'])} caps" for r in records]
        await event.edit(render("PLUGIN // CATALOG", rows[:60] or ["No plugins."], footer="system_ops | plugin"))
        return
    if action == "search":
        if not arg:
            raise CommandError(f"Usage: {config.PREFIX}plugin search <query>")
        needle = arg.lower()
        rows = [f"{_plugin_name(r['name'])} · {r['state']} · {r['description'][:100]}" for r in records if needle in (r['name'] + " " + r['description'] + " " + " ".join(r['capabilities'])).lower()]
        await event.edit(render("PLUGIN // SEARCH", rows[:40] or ["No matching plugins."], footer="system_ops | plugin search"))
        return
    record = _find_plugin(records, arg)
    if action == "health":
        rows = [f"State: {record['state']}", f"Error: {record['error'] or 'none'}", f"Critical: {'yes' if record['critical'] else 'no'}", f"Dependencies: {', '.join(_plugin_name(x) for x in record['dependencies']) or 'none'}"]
        await event.edit(render("PLUGIN // HEALTH", rows, footer="system_ops | plugin health"))
        return
    if action in {"enable", "install"}:
        await manager.enable_plugin(record["name"])
        await event.edit(render("PLUGIN // ENABLED", [record["name"], "Compatibility: checked", "Dependencies: running", "Lifecycle: RUNNING"], footer="system_ops | plugin"))
        return
    if action == "disable":
        await manager.disable_plugin(record["name"])
        await event.edit(render("PLUGIN // DISABLED", [record["name"], "Owned registrations removed", "Durable state preserved"], footer="system_ops | plugin"))
        return
    if action == "reload":
        await manager.disable_plugin(record["name"])
        await manager.enable_plugin(record["name"])
        await event.edit(render("PLUGIN // RELOADED", [record["name"], "Lifecycle: RUNNING"], footer="system_ops | plugin"))
        return


async def handle_aiux(event):
    action = (event.pattern_match.group(1) or "summarize").lower()
    arg = (event.pattern_match.group(2) or "").strip()
    ctx = _ctx()
    ai = ctx.get("ai")
    if action in {"summarize", "explain"}:
        reply = await event.get_reply_message()
        text = getattr(reply, "raw_text", "") if reply is not None else arg
        if not text:
            raise CommandError(f"Reply to a message or use {config.PREFIX}aiux {action} <text>.")
        prompt = text[:50_000]
        if action == "summarize":
            result = await ai.summarize(prompt)
        else:
            result = await ai.chat([
                {"role": "system", "content": "Explain the supplied content using only the provided context. State uncertainty instead of inventing facts."},
                {"role": "user", "content": prompt},
            ])
        await event.edit(render(f"AI // {action.upper()}", [result.text[:7000], f"Provider: {result.provider} · Model: {result.model}"], footer="ai | advisory | no mutation"))
        return
    if action == "search":
        if not arg:
            raise CommandError(f"Usage: {config.PREFIX}aiux search <query>")
        results = await ctx.get("search").search(arg, limit=12)
        context_text = "\n".join(f"[{item.source}:{item.ref}] {item.title}: {item.snippet}" for item in results)
        if not context_text:
            raise CommandError("Search returned no evidence to synthesize.")
        result = await ai.chat([
            {"role": "system", "content": "Synthesize only the supplied search evidence. Cite source/ref identifiers. Mark uncertainty explicitly."},
            {"role": "user", "content": context_text[:45_000]},
        ])
        await event.edit(render("AI // SEARCH SYNTHESIS", [result.text[:7000], "Evidence: " + ", ".join(f"{x.source}:{x.ref}" for x in results[:8])], footer="ai | evidence-linked | advisory"))
        return
    if action == "evidence":
        if not arg:
            raise CommandError(f"Usage: {config.PREFIX}aiux evidence <target>")
        evidence = await inspect_target(arg)
        result = await ai.chat([
            {"role": "system", "content": "Explain the supplied evidence without upgrading possible or derived relationships into facts."},
            {"role": "user", "content": "\n".join(evidence)[:45_000]},
        ])
        await event.edit(render("AI // EVIDENCE EXPLANATION", [result.text[:7000]], footer="ai | evidence | advisory"))
        return
    if action == "case":
        if not arg:
            raise CommandError(f"Usage: {config.PREFIX}aiux case <case-id>")
        report = await ctx.get("cases").report(arg)
        result = await ai.chat([
            {"role": "system", "content": "Draft a factual investigation report from the supplied case record. Preserve observed/derived distinctions and identify unknowns."},
            {"role": "user", "content": report[:45_000]},
        ])
        await event.edit(render("AI // CASE REPORT DRAFT", [result.text[:7000]], footer="ai | case | draft | advisory"))
        return
    if action == "timeline":
        if not arg:
            raise CommandError(f"Usage: {config.PREFIX}aiux timeline <case-id>")
        timeline = await ctx.get("cases").timeline(arg, limit=100)
        context_text = "\n".join(f"{item['event_at']} [{item['kind']}] {item['description']}" for item in timeline)
        result = await ai.chat([
            {"role": "system", "content": "Summarize the timeline chronologically and identify uncertainty. Do not invent missing events."},
            {"role": "user", "content": context_text[:45_000]},
        ])
        await event.edit(render("AI // TIMELINE SUMMARY", [result.text[:7000]], footer="ai | timeline | advisory"))
        return
    if action == "media":
        reply = await event.get_reply_message()
        media = getattr(reply, "media", None) if reply is not None else None
        if not media:
            raise CommandError("Reply to media for OCR/STT → AI.")
        workspace = await ctx.get("media").create_workspace("aiux_media")
        try:
            downloaded = await ctx.get("media").download_telegram_media(event.client.download_media, media, workspace=workspace)
            if not downloaded:
                raise CommandError("Media download failed.")
            analysis = await ctx.get("media_intel").analyze_file(downloaded)
            material = "\n".join(str(analysis.get(key) or "") for key in ("ocr_text", "transcript") if analysis.get(key))
            if not material:
                raise CommandError("No OCR/transcript evidence was produced.")
            result = await ai.chat([
                {"role": "system", "content": "Analyze only the OCR/transcript evidence. Mark uncertainty and do not invent visual/audio facts."},
                {"role": "user", "content": material[:45_000]},
            ])
        finally:
            await ctx.get("media").cleanup(workspace)
        await event.edit(render("AI // MEDIA", [result.text[:7000]], footer="ai | OCR/STT | advisory"))
        return
    raise CommandError(f"Unknown AI UX action: {action}")


async def handle_control(event):
    action = event.pattern_match.group(1).lower()
    arg = (event.pattern_match.group(2) or "").strip()
    ctx = _ctx()
    if action == "doctor":
        rows = []
        integrity = await ctx.get("storage").integrity_check()
        rows.append(f"Database integrity: {'PASS' if integrity else 'FAIL'}")
        rows.append(f"Search ready: {'YES' if getattr(ctx.get('search'), '_ready', False) else 'NO'}")
        ai_diag = ctx.get("ai").diagnostics()
        rows.append(f"AI provider: {ai_diag['provider']} · remote={'ON' if ai_diag['remote_enabled'] else 'OFF'}")
        isolation = ctx.get("isolation").assess()
        rows.append(f"Isolation: {isolation.backend} · {'PASS' if isolation.available else 'FAIL'}")
        records = _manager(event).snapshot()
        rows.append(f"Plugins: {sum(r['state'] == 'RUNNING' for r in records)}/{len(records)} running")
        jobs = await ctx.get("jobs").list(limit=100)
        rows.append(f"Jobs sampled: {len(jobs)}")
        attention = [r for r in records if r["state"] in {"FAILED_IMPORT", "FAILED_SETUP"}]
        rows.append(f"Plugin failures: {len(attention)}")
        await event.edit(render("DOCTOR // PLATFORM", rows, footer="system_ops | doctor | safe diagnostics"))
        return
    if action == "config":
        allowed = ("PREFIX", "OWNER_ID", "DATABASE_PATH", "AI_PROVIDER", "AI_REMOTE_ENABLED", "LOG_LEVEL")
        rows = []
        for name in allowed:
            value = getattr(config, name, None)
            if name in {"OWNER_ID"}:
                value = "configured" if value else "unset"
            rows.append(f"{name}: {value}")
        await event.edit(render("CONFIG // SAFE VIEW", rows, footer="system_ops | redacted | read-only"))
        return
    if action == "update":
        mode = arg.lower() or "check"
        root = Path(ctx.project_root)
        def run_git(args):
            return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20, check=False)
        status = await asyncio.to_thread(run_git, ["status", "--porcelain"])
        if status.returncode != 0:
            raise CommandError("Unable to inspect git state.")
        if status.stdout.strip():
            raise CommandError("Update blocked: working tree is dirty.")
        head = await asyncio.to_thread(run_git, ["rev-parse", "HEAD"])
        remote = await asyncio.to_thread(run_git, ["rev-parse", "@{u}"])
        if head.returncode != 0 or remote.returncode != 0:
            raise CommandError("Unable to resolve repository/upstream state.")
        rows = [f"HEAD: {head.stdout.strip()[:12]}", f"Upstream: {remote.stdout.strip()[:12]}", f"Working tree: CLEAN"]
        if mode == "apply":
            pull = await asyncio.to_thread(run_git, ["pull", "--ff-only"])
            if pull.returncode != 0:
                raise CommandError("Fast-forward update failed; no destructive fallback was attempted.")
            rows += ["Update: APPLIED", "Restart required if code changed."]
        elif mode != "check":
            raise CommandError(f"Usage: {config.PREFIX}update <check|apply>")
        else:
            rows += ["Update: preflight only; no code changed."]
        await event.edit(render("UPDATE // CONTROL PLANE", rows, footer="system_ops | safe update"))
        return
    if action == "restart":
        if arg.lower() != "confirm":
            raise CommandError(f"Restart is explicit. Use {config.PREFIX}restart confirm.")
        await event.edit(render("RESTART // CONTROL PLANE", ["Restart requested.", "Systemd/process supervisor is expected to restart Astra."], footer="system_ops | restart"))
        os.kill(os.getpid(), signal.SIGTERM)
        return
    raise CommandError("Unknown control action.")
