"""Operator surface for the durable Automation Engine (Program G)."""
from __future__ import annotations

import asyncio
import json
import logging

from telethon import events

from config import config
from core.context import get_application_context
from core.errors import CommandError
from core.registry import register_cmd
from helpers.hud import render

logger = logging.getLogger("astra.plugin.automation")
_job_task: asyncio.Task[None] | None = None


def _engine():
    context = get_application_context()
    if context is None:
        raise CommandError("Automation Engine is unavailable.")
    return context.get("automation"), context


async def setup(client):
    global _job_task
    p = config.PREFIX
    register_cmd(client, rf"^{p}autorule\s+list$", handle_list, "automation", "List automation rules.")
    register_cmd(client, rf"^{p}autorule\s+show\s+(\S+)$", handle_show, "automation", "Show one automation rule.")
    register_cmd(client, rf"^{p}autorule\s+create\s+(\S+)\s+(.+)$", handle_create, "automation", "Create/update a declarative automation rule from JSON.")
    register_cmd(client, rf"^{p}autorule\s+(enable|disable|delete)\s+(\S+)$", handle_state, "automation", "Enable, disable or delete an automation rule.")
    register_cmd(client, rf"^{p}autorule\s+run\s+(\S+)$", handle_run, "automation", "Run an OWNER_COMMAND automation rule.")
    register_cmd(client, rf"^{p}autostatus$", handle_status, "automation", "Show Automation Engine status.")
    context = get_application_context()
    if context is not None:
        _job_task = context.tasks.create_task(_job_completion_worker(context), name="automation.job_completion_worker", owner="automation")


async def shutdown(_client):
    global _job_task
    if _job_task is not None:
        _job_task.cancel()
        await asyncio.gather(_job_task, return_exceptions=True)
        _job_task = None


async def handle_list(event):
    engine, _ = _engine()
    rules = await engine.list_rules(limit=100)
    rows = [f"`{r.id}` · {'ON' if r.enabled else 'OFF'} · v{r.version} · {r.trigger.get('type')} · {len(r.actions)} action(s)" for r in rules]
    await event.edit(render("AUTOMATION RULES", rows or ["No automation rules."], footer="automation | autorule list"))


async def handle_show(event):
    engine, _ = _engine()
    rule = await engine.get_rule(event.pattern_match.group(1).lower())
    text = json.dumps(rule.snapshot(), indent=2, ensure_ascii=False)
    await event.edit(f"<pre>{_escape(text[:12000])}</pre>")


async def handle_create(event):
    engine, _ = _engine()
    rule_id = event.pattern_match.group(1).lower()
    try:
        spec = json.loads(event.pattern_match.group(2))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid rule JSON: {exc.msg}") from exc
    if not isinstance(spec, dict):
        raise CommandError("Rule JSON must be an object.")
    rule = await engine.create_rule(
        rule_id=rule_id,
        trigger=spec.get("trigger", {}),
        scope=spec.get("scope", {}),
        match=spec.get("match", {}),
        actions=spec.get("actions", []),
        cooldown_seconds=float(spec.get("cooldown_seconds", 0)),
        max_runs=int(spec.get("max_runs", 0)),
    )
    await event.edit(render("AUTOMATION RULE", [f"ID: `{rule.id}`", f"Version: `{rule.version}`", f"Trigger: `{rule.trigger.get('type')}`", f"Actions: `{len(rule.actions)}`", "State: `ENABLED`"], footer="automation | rule saved"))


async def handle_state(event):
    engine, _ = _engine()
    action = event.pattern_match.group(1).lower()
    rule_id = event.pattern_match.group(2).lower()
    if action == "delete":
        await engine.delete_rule(rule_id)
        await event.edit(render("AUTOMATION RULE", [f"Deleted `{rule_id}`."], footer="automation | rule delete"))
        return
    await engine.set_enabled(rule_id, action == "enable")
    await event.edit(render("AUTOMATION RULE", [f"`{rule_id}` → `{'ENABLED' if action == 'enable' else 'DISABLED'}`"], footer="automation | rule state"))


async def handle_run(event):
    engine, _ = _engine()
    rule_id = event.pattern_match.group(1).lower()
    accepted = await engine.run_owner_command(rule_id, {"source_peer": str(event.chat_id) if event.chat_id is not None else None, "command": "autorule run"})
    await event.edit(render("AUTOMATION RUN", [f"Rule: `{rule_id}`", f"Accepted: `{accepted}`", "Execution: `DURABLE JOB`"], footer="automation | autorule run"))


async def handle_status(event):
    engine, context = _engine()
    rules = await engine.list_rules(limit=1000)
    enabled = sum(1 for r in rules if r.enabled)
    jobs = await context.get("jobs").list(limit=100)
    automation_jobs = [j for j in jobs if j.type == "AUTOMATION_RUN"]
    rows = [f"Rules: `{len(rules)}`", f"Enabled: `{enabled}`", f"Recent automation jobs: `{len(automation_jobs)}`", "Triggers: `MESSAGE_NEW MESSAGE_EDIT MEDIA_OBSERVED SCHEDULED JOB_COMPLETED INTELLIGENCE_OBSERVED OWNER_COMMAND`", "Actions: `REPLY FORWARD TAG INDEX ARCHIVE NOTIFY_OWNER PLUGIN_ACTION START_JOB`"]
    await event.edit(render("AUTOMATION", rows, footer="automation | status"))


async def _job_completion_worker(context):
    jobs = context.get("jobs")
    engine = context.get("automation")
    cursor = 0
    while True:
        try:
            rows = await context.get("storage").fetchall("SELECT id, job_id, event_type, payload_json FROM job_events WHERE id>? AND event_type IN ('COMPLETED','FAILED') ORDER BY id LIMIT 100", (cursor,))
            for row in rows:
                cursor = max(cursor, int(row[0]))
                job_id = str(row[1])
                try:
                    job = await jobs.get(job_id)
                except KeyError:
                    continue
                await engine.handle_job_completion(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automation job completion worker iteration failed")
        await asyncio.sleep(2)


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
