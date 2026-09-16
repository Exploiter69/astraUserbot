"""Durable declarative automation engine for Program G.

Automation deliberately separates observation, rule evaluation, authorization and
execution. Telegram side effects use TelegramFacade; restart-sensitive execution
uses the existing JobEngine. Rules are owner-controlled, versioned and bounded.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core.errors import CommandError
from core.services.jobs import Job, JobError
from core.services.telegram_events import TelegramEvent

logger = logging.getLogger("astra.automation")

RULE_SCHEMA_VERSION = 1
AUTOMATION_JOB_TYPE = "AUTOMATION_RUN"
MAX_RULES = 1000
MAX_ACTIONS = 16
MAX_ACTION_PAYLOAD = 64 * 1024
MAX_MATCH_TEXT = 4096
MAX_RUNS = 1000
MAX_TRIGGER_BURST = 32
SCHEDULE_POLL_SECONDS = 5.0

TRIGGERS = {
    "MESSAGE_NEW",
    "MESSAGE_EDIT",
    "MEDIA_OBSERVED",
    "SCHEDULED",
    "JOB_COMPLETED",
    "INTELLIGENCE_OBSERVED",
    "OWNER_COMMAND",
}
ACTIONS = {
    "REPLY",
    "FORWARD",
    "TAG",
    "INDEX",
    "ARCHIVE",
    "NOTIFY_OWNER",
    "PLUGIN_ACTION",
    "START_JOB",
}
SIDE_EFFECTS = {"READ", "WRITE", "BULK", "DESTRUCTIVE"}


class AutomationError(RuntimeError):
    """Controlled automation validation/execution failure."""


@dataclass(frozen=True, slots=True)
class AutomationRule:
    id: str
    version: int
    enabled: bool
    owner: str
    trigger: dict[str, Any]
    scope: dict[str, Any]
    match: dict[str, Any]
    actions: tuple[dict[str, Any], ...]
    cooldown_seconds: float
    max_runs: int
    created_at: float
    updated_at: float

    @property
    def name(self) -> str:
        return self.id

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "enabled": self.enabled,
            "owner": self.owner,
            "trigger": self.trigger,
            "scope": self.scope,
            "match": self.match,
            "actions": list(self.actions),
            "cooldown_seconds": self.cooldown_seconds,
            "max_runs": self.max_runs,
        }


ActionHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[Any]]


class AutomationEngine:
    """Own declarative rules and turn matched events into durable runs."""

    def __init__(self, storage: Any, jobs: Any, telegram: Any, *, owner_id: int | str) -> None:
        self.storage = storage
        self.jobs = jobs
        self.telegram = telegram
        self.owner_id = str(owner_id)
        self._schedule_task: asyncio.Task[None] | None = None
        self._started = False
        self._action_handlers: dict[str, tuple[ActionHandler, str]] = {}
        self._last_trigger: dict[tuple[str, str], float] = {}

    async def start(self) -> None:
        if self._started:
            return
        await self._ensure_schema()
        if AUTOMATION_JOB_TYPE not in self.jobs.handlers:
            self.jobs.register_handler(AUTOMATION_JOB_TYPE, self._handle_job)
        self._schedule_task = asyncio.create_task(self._schedule_loop(), name="automation.scheduler")
        self._started = True
        logger.info("Automation Engine started")

    async def close(self) -> None:
        task = self._schedule_task
        self._schedule_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._started = False

    async def _ensure_schema(self) -> None:
        await self.storage.execute(
            "CREATE TABLE IF NOT EXISTS automation_schema (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        row = await self.storage.fetchone("SELECT version FROM automation_schema ORDER BY version DESC LIMIT 1")
        if row is None:
            await self.storage.transaction([
                ("CREATE TABLE IF NOT EXISTS automation_rules (id TEXT PRIMARY KEY, version INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, owner TEXT NOT NULL, trigger_json TEXT NOT NULL, scope_json TEXT NOT NULL, match_json TEXT NOT NULL, actions_json TEXT NOT NULL, cooldown_seconds REAL NOT NULL DEFAULT 0, max_runs INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL)", ()),
                ("CREATE INDEX IF NOT EXISTS idx_automation_rules_enabled ON automation_rules(enabled, updated_at DESC)", ()),
                ("CREATE INDEX IF NOT EXISTS idx_automation_rules_trigger ON automation_rules(trigger_json)", ()),
                ("CREATE TABLE IF NOT EXISTS automation_runs (run_id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, rule_version INTEGER NOT NULL, trigger_event_id TEXT, trigger_type TEXT NOT NULL, state TEXT NOT NULL, action_index INTEGER NOT NULL DEFAULT 0, started_at REAL, completed_at REAL, error_code TEXT, error_message TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL, FOREIGN KEY(rule_id) REFERENCES automation_rules(id) ON DELETE RESTRICT)", ()),
                ("CREATE INDEX IF NOT EXISTS idx_automation_runs_rule ON automation_runs(rule_id, created_at DESC)", ()),
                ("CREATE INDEX IF NOT EXISTS idx_automation_runs_state ON automation_runs(state, updated_at)", ()),
                ("CREATE TABLE IF NOT EXISTS automation_action_runs (run_id TEXT NOT NULL, action_index INTEGER NOT NULL, action_type TEXT NOT NULL, state TEXT NOT NULL, idempotency_key TEXT NOT NULL, started_at REAL, completed_at REAL, result_json TEXT, error_code TEXT, error_message TEXT, PRIMARY KEY(run_id, action_index), UNIQUE(idempotency_key), FOREIGN KEY(run_id) REFERENCES automation_runs(run_id) ON DELETE CASCADE)", ()),
                ("CREATE TABLE IF NOT EXISTS automation_cooldowns (rule_id TEXT NOT NULL, cooldown_key TEXT NOT NULL, last_run_at REAL NOT NULL, PRIMARY KEY(rule_id, cooldown_key), FOREIGN KEY(rule_id) REFERENCES automation_rules(id) ON DELETE CASCADE)", ()),
                ("INSERT INTO automation_schema(version, applied_at) VALUES (1, ?)", (time.time(),)),
            ])
        elif int(row[0]) != RULE_SCHEMA_VERSION:
            raise AutomationError(f"Unsupported automation schema version: {row[0]}")

    def register_action_handler(self, name: str, handler: ActionHandler, *, side_effect: str = "WRITE") -> None:
        name = self._token(name, 64).upper()
        if name not in ACTIONS:
            raise AutomationError(f"Unsupported action type: {name}")
        if side_effect not in SIDE_EFFECTS:
            raise AutomationError("Invalid action side-effect class")
        if not callable(handler):
            raise TypeError("Automation action handler must be callable")
        self._action_handlers[name] = (handler, side_effect)

    async def create_rule(
        self,
        *,
        rule_id: str,
        trigger: dict[str, Any],
        scope: dict[str, Any],
        match: dict[str, Any],
        actions: list[dict[str, Any]],
        cooldown_seconds: float = 0,
        max_runs: int = 0,
        owner: str | None = None,
    ) -> AutomationRule:
        rid = self._token(rule_id, 64).lower()
        if owner is not None and str(owner) != self.owner_id:
            raise AutomationError("Automation rules can only be owned by the configured owner")
        self._validate_rule(trigger, scope, match, actions, cooldown_seconds, max_runs)
        count = await self.storage.fetchone("SELECT COUNT(*) FROM automation_rules")
        if int(count[0]) >= MAX_RULES:
            raise AutomationError("Automation rule limit reached")
        now = time.time()
        payload = (rid, RULE_SCHEMA_VERSION, 1, self.owner_id, self._dump(trigger), self._dump(scope), self._dump(match), self._dump(actions), float(cooldown_seconds), int(max_runs), now, now)
        await self.storage.execute(
            "INSERT INTO automation_rules(id,version,enabled,owner,trigger_json,scope_json,match_json,actions_json,cooldown_seconds,max_runs,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,enabled=1,owner=excluded.owner,trigger_json=excluded.trigger_json,scope_json=excluded.scope_json,match_json=excluded.match_json,actions_json=excluded.actions_json,cooldown_seconds=excluded.cooldown_seconds,max_runs=excluded.max_runs,updated_at=excluded.updated_at",
            payload,
        )
        await self.storage.execute(
            "INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)",
            ("AUTOMATION_RULE_UPSERT", rid, self._dump({"version": RULE_SCHEMA_VERSION}), now),
        )
        return await self.get_rule(rid)

    async def get_rule(self, rule_id: str) -> AutomationRule:
        row = await self.storage.fetchone("SELECT * FROM automation_rules WHERE id=?", (rule_id,))
        if row is None:
            raise KeyError(rule_id)
        return self._row_to_rule(row)

    async def list_rules(self, *, include_disabled: bool = True, limit: int = 100) -> list[AutomationRule]:
        limit = max(1, min(int(limit), 100))
        if include_disabled:
            rows = await self.storage.fetchall("SELECT * FROM automation_rules ORDER BY created_at DESC LIMIT ?", (limit,))
        else:
            rows = await self.storage.fetchall("SELECT * FROM automation_rules WHERE enabled=1 ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row_to_rule(row) for row in rows]

    async def set_enabled(self, rule_id: str, enabled: bool) -> None:
        rule = await self.get_rule(rule_id)
        await self.storage.execute("UPDATE automation_rules SET enabled=?,updated_at=? WHERE id=?", (int(enabled), time.time(), rule.id))
        await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("AUTOMATION_RULE_STATE", rule.id, self._dump({"enabled": bool(enabled)}), time.time()))

    async def delete_rule(self, rule_id: str) -> None:
        rule = await self.get_rule(rule_id)
        active = await self.storage.fetchone("SELECT COUNT(*) FROM automation_runs WHERE rule_id=? AND state IN ('QUEUED','RUNNING','RECOVERY_REQUIRED')", (rule.id,))
        if int(active[0]) > 0:
            raise AutomationError("Cannot delete a rule with active runs; disable it instead")
        await self.storage.execute("DELETE FROM automation_rules WHERE id=?", (rule.id,))
        await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("AUTOMATION_RULE_DELETE", rule.id, "{}", time.time()))

    async def trigger(self, event: TelegramEvent | dict[str, Any], *, trigger_type: str | None = None) -> int:
        data = event.as_dict() if isinstance(event, TelegramEvent) else dict(event)
        kind = trigger_type or str(data.get("event_type") or data.get("trigger_type") or "").upper()
        if kind not in TRIGGERS:
            return 0
        rules = await self.list_rules(include_disabled=False, limit=MAX_TRIGGER_BURST)
        accepted = 0
        for rule in rules:
            if rule.trigger.get("type") != kind:
                continue
            if not self._scope_matches(rule.scope, data):
                continue
            if not self._match_matches(rule.match, data):
                continue
            cooldown_key = self._cooldown_key(rule, data)
            now = time.time()
            previous = self._last_trigger.get((rule.id, cooldown_key), 0.0)
            if rule.cooldown_seconds and now - previous < rule.cooldown_seconds:
                continue
            if rule.cooldown_seconds:
                row = await self.storage.fetchone("SELECT last_run_at FROM automation_cooldowns WHERE rule_id=? AND cooldown_key=?", (rule.id, cooldown_key))
                if row and now - float(row[0]) < rule.cooldown_seconds:
                    continue
            if rule.max_runs:
                row = await self.storage.fetchone("SELECT COUNT(*) FROM automation_runs WHERE rule_id=?", (rule.id,))
                if int(row[0]) >= rule.max_runs:
                    continue
            run_id = uuid.uuid4().hex
            event_id = str(data.get("event_id") or data.get("id") or uuid.uuid4().hex)
            idem = hashlib.sha256(f"{rule.id}:{rule.version}:{event_id}".encode()).hexdigest()
            job = await self.jobs.enqueue(
                AUTOMATION_JOB_TYPE,
                {"rule_id": rule.id, "rule_version": rule.version, "event": self._bound(data)},
                owner=self.owner_id,
                idempotency_key=f"automation:{idem}",
                max_attempts=3,
                priority=2,
                resource_class="automation",
            )
            await self.storage.execute(
                "INSERT INTO automation_runs(run_id,rule_id,rule_version,trigger_event_id,trigger_type,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, rule.id, rule.version, event_id, kind, "QUEUED", now, now),
            )
            await self.storage.execute(
                "INSERT INTO automation_cooldowns(rule_id,cooldown_key,last_run_at) VALUES(?,?,?) ON CONFLICT(rule_id,cooldown_key) DO UPDATE SET last_run_at=excluded.last_run_at",
                (rule.id, cooldown_key, now),
            )
            self._last_trigger[(rule.id, cooldown_key)] = now
            await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("AUTOMATION_RUN_ENQUEUED", run_id, self._dump({"job_id": job.id, "rule_id": rule.id, "trigger": kind}), now))
            accepted += 1
        return accepted

    async def run_owner_command(self, rule_id: str, event: dict[str, Any] | None = None) -> int:
        rule = await self.get_rule(rule_id)
        if rule.owner != self.owner_id:
            raise AutomationError("Rule owner mismatch")
        return await self.trigger({"event_id": uuid.uuid4().hex, "event_type": "OWNER_COMMAND", "source_peer": (event or {}).get("source_peer"), "payload": event or {}}, trigger_type="OWNER_COMMAND")

    async def _handle_job(self, job: Job) -> dict[str, Any]:
        payload = job.payload
        rule = await self.get_rule(str(payload.get("rule_id", "")))
        if rule.version != int(payload.get("rule_version", -1)):
            raise JobError("Rule version changed after enqueue; refusing stale automation execution", code="AUTOMATION_RULE_VERSION_STALE", retryable=False)
        run = await self.storage.fetchone("SELECT * FROM automation_runs WHERE run_id=?", (self._run_id_for_job(job),))
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            rows = await self.storage.fetchall("SELECT run_id FROM automation_runs WHERE rule_id=? AND trigger_event_id=? ORDER BY created_at DESC LIMIT 1", (rule.id, str(payload.get("event", {}).get("event_id", ""))))
            run_id = str(rows[0][0]) if rows else uuid.uuid4().hex
        now = time.time()
        await self.storage.execute("UPDATE automation_runs SET state='RUNNING',started_at=COALESCE(started_at,?),updated_at=? WHERE run_id=?", (now, now, run_id))
        event = self._bound(dict(payload.get("event") or {}))
        try:
            for index, action in enumerate(rule.actions):
                existing = await self.storage.fetchone("SELECT state FROM automation_action_runs WHERE run_id=? AND action_index=?", (run_id, index))
                if existing and existing[0] == "COMPLETED":
                    continue
                action_type = str(action.get("type", "")).upper()
                key = hashlib.sha256(f"{run_id}:{index}:{rule.version}".encode()).hexdigest()
                await self.storage.execute("INSERT INTO automation_action_runs(run_id,action_index,action_type,state,idempotency_key,started_at) VALUES(?,?,?,?,?,?) ON CONFLICT(run_id,action_index) DO UPDATE SET state='STARTED',started_at=excluded.started_at", (run_id, index, action_type, "STARTED", key, time.time()))
                await self.storage.execute("UPDATE automation_runs SET action_index=?,updated_at=? WHERE run_id=?", (index, time.time(), run_id))
                await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("ACTION_STARTED", run_id, self._dump({"index": index, "type": action_type}), time.time()))
                try:
                    result = await self._execute_action(action, event, rule, key)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self.storage.execute("UPDATE automation_action_runs SET state='FAILED',error_code=?,error_message=? WHERE run_id=? AND action_index=?", (type(exc).__name__, str(exc)[:500], run_id, index))
                    await self.storage.execute("UPDATE automation_runs SET state='RECOVERY_REQUIRED',error_code=?,error_message=?,updated_at=? WHERE run_id=?", (type(exc).__name__, str(exc)[:500], time.time(), run_id))
                    await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("STEP_FAILED", run_id, self._dump({"index": index, "type": action_type, "error": type(exc).__name__}), time.time()))
                    raise JobError(str(exc)[:500], code="AUTOMATION_STEP_FAILED", retryable=False) from exc
                await self.storage.execute("UPDATE automation_action_runs SET state='COMPLETED',completed_at=?,result_json=? WHERE run_id=? AND action_index=?", (time.time(), self._dump(result), run_id, index))
                await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("STEP_COMPLETED", run_id, self._dump({"index": index, "type": action_type}), time.time()))
            await self.storage.execute("UPDATE automation_runs SET state='COMPLETED',completed_at=?,updated_at=? WHERE run_id=?", (time.time(), time.time(), run_id))
            return {"run_id": run_id, "state": "COMPLETED", "actions": len(rule.actions)}
        except asyncio.CancelledError:
            await self.storage.execute("UPDATE automation_runs SET state='RECOVERY_REQUIRED',error_code='WORKER_CANCELLED',updated_at=? WHERE run_id=?", (time.time(), run_id))
            raise

    async def _execute_action(self, action: dict[str, Any], event: dict[str, Any], rule: AutomationRule, idempotency_key: str) -> Any:
        action_type = str(action.get("type", "")).upper()
        self._validate_action(action)
        target = action.get("target")
        if target is not None and rule.scope.get("chat_id") is not None and str(target) != str(rule.scope["chat_id"]):
            raise AutomationError("Action target broadens rule scope")
        if action_type == "REPLY":
            peer = event.get("source_peer")
            text = str(action.get("text", ""))[:4000]
            if peer is None or not text:
                raise AutomationError("REPLY requires event peer and bounded text")
            return await self.telegram.send_message(self._telegram_target(peer), text, reply_to=event.get("message_id"))
        if action_type == "FORWARD":
            peer = event.get("source_peer")
            destination = action.get("destination")
            message_id = event.get("message_id")
            if peer is None or destination is None or message_id is None:
                raise AutomationError("FORWARD requires source, destination and message")
            if rule.scope.get("chat_id") is not None and str(destination) != str(rule.scope["chat_id"]):
                raise AutomationError("FORWARD destination is outside rule scope")
            return await self.telegram.client.forward_messages(destination, peer, message_id)
        if action_type in {"TAG", "INDEX"}:
            tag = self._token(str(action.get("tag", action.get("value", "automation"))), 64)
            await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", (f"AUTOMATION_{action_type}", str(event.get("event_id", idempotency_key)), self._dump({"tag": tag, "peer": event.get("source_peer"), "message_id": event.get("message_id")}), time.time()))
            return {"tag": tag}
        if action_type == "ARCHIVE":
            if "TELEGRAM_ARCHIVE" not in self.jobs.handlers:
                raise AutomationError("Archive job handler is unavailable")
            peer = str(action.get("peer") or event.get("source_peer") or "")
            if not peer:
                raise AutomationError("ARCHIVE requires a peer")
            if rule.scope.get("chat_id") is not None and peer != str(rule.scope["chat_id"]):
                raise AutomationError("ARCHIVE peer is outside rule scope")
            return await self.jobs.enqueue("TELEGRAM_ARCHIVE", {"peer": peer, "limit": max(1, min(int(action.get("limit", 100)), 100)), "min_message_id": max(0, int(action.get("min_message_id", 0))), "include_media": bool(action.get("include_media", False))}, owner=self.owner_id, idempotency_key=f"{idempotency_key}:archive", priority=3, resource_class="telegram")
        if action_type == "NOTIFY_OWNER":
            text = str(action.get("text", "Automation notification"))[:4000]
            return await self.telegram.send_message(int(self.owner_id), text)
        if action_type == "START_JOB":
            job_type = self._token(str(action.get("job_type", "")), 128)
            if job_type not in self.jobs.handlers or job_type == AUTOMATION_JOB_TYPE:
                raise AutomationError("START_JOB target is not an approved registered job")
            payload = action.get("payload") or {}
            if not isinstance(payload, dict):
                raise AutomationError("START_JOB payload must be an object")
            if len(self._dump(payload).encode()) > MAX_ACTION_PAYLOAD:
                raise AutomationError("START_JOB payload exceeds automation bound")
            return await self.jobs.enqueue(job_type, payload, owner=self.owner_id, parent_id=None, idempotency_key=f"{idempotency_key}:job", priority=2, resource_class=str(action.get("resource_class", "automation"))[:64])
        handler_entry = self._action_handlers.get(action_type)
        if handler_entry is None:
            raise AutomationError(f"No approved handler registered for action: {action_type}")
        handler, _side_effect = handler_entry
        return await handler(dict(action), dict(event))

    async def _schedule_loop(self) -> None:
        while True:
            try:
                rules = await self.list_rules(include_disabled=False, limit=MAX_RULES)
                now = time.time()
                for rule in rules:
                    if rule.trigger.get("type") != "SCHEDULED":
                        continue
                    due = float(rule.trigger.get("at", 0))
                    interval = max(0.0, float(rule.trigger.get("interval_seconds", 0)))
                    if due <= 0 or due > now:
                        continue
                    key = "schedule"
                    last = self._last_trigger.get((rule.id, key), 0.0)
                    if last and (interval <= 0 or now - last < interval):
                        continue
                    await self.trigger({"event_id": f"schedule:{rule.id}:{int(now)}", "event_type": "SCHEDULED", "observed_at": now, "source_peer": rule.scope.get("chat_id"), "payload": {"scheduled_at": due}}, trigger_type="SCHEDULED")
                    self._last_trigger[(rule.id, key)] = now
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Automation scheduler iteration failed")
            await asyncio.sleep(SCHEDULE_POLL_SECONDS)

    def _validate_rule(self, trigger: dict[str, Any], scope: dict[str, Any], match: dict[str, Any], actions: list[dict[str, Any]], cooldown: float, max_runs: int) -> None:
        if not isinstance(trigger, dict) or str(trigger.get("type", "")).upper() not in TRIGGERS:
            raise AutomationError("Invalid automation trigger")
        if not isinstance(scope, dict) or not scope:
            raise AutomationError("Automation scope must be explicit")
        if not isinstance(match, dict):
            raise AutomationError("Automation match must be an object")
        if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
            raise AutomationError("Automation requires 1-16 actions")
        if cooldown < 0 or cooldown > 7 * 86400:
            raise AutomationError("Cooldown must be 0-7 days")
        if max_runs < 0 or max_runs > 100000:
            raise AutomationError("max_runs must be 0-100000")
        for action in actions:
            self._validate_action(action)
        if trigger.get("type") in {"MESSAGE_NEW", "MESSAGE_EDIT", "MEDIA_OBSERVED"} and scope.get("chat_id") is None:
            raise AutomationError("Telegram event rules require an explicit chat_id scope")

    def _validate_action(self, action: dict[str, Any]) -> None:
        if not isinstance(action, dict):
            raise AutomationError("Automation action must be an object")
        action_type = str(action.get("type", "")).upper()
        if action_type not in ACTIONS:
            raise AutomationError(f"Unsupported automation action: {action_type}")
        if len(self._dump(action).encode("utf-8")) > MAX_ACTION_PAYLOAD:
            raise AutomationError("Automation action payload exceeds bound")
        if action_type == "REPLY" and len(str(action.get("text", ""))) > 4000:
            raise AutomationError("Reply text exceeds bound")
        if action_type == "FORWARD" and not action.get("destination"):
            raise AutomationError("FORWARD requires a destination")
        if action_type == "START_JOB" and not action.get("job_type"):
            raise AutomationError("START_JOB requires a job_type")
        if action_type == "PLUGIN_ACTION" and not action.get("name"):
            raise AutomationError("PLUGIN_ACTION requires a registered action name")

    @staticmethod
    def _scope_matches(scope: dict[str, Any], event: dict[str, Any]) -> bool:
        peer = scope.get("chat_id")
        if peer is not None and str(event.get("source_peer")) != str(peer):
            return False
        entity = scope.get("entity_id")
        if entity is not None and str(event.get("entity_id")) != str(entity):
            return False
        return True

    @staticmethod
    def _match_matches(match: dict[str, Any], event: dict[str, Any]) -> bool:
        payload = event.get("payload") or {}
        text = str(payload.get("text") or event.get("text") or "")[:MAX_MATCH_TEXT]
        if "contains" in match and str(match["contains"]).lower() not in text.lower():
            return False
        if "equals" in match and text != str(match["equals"]):
            return False
        if "prefix" in match and not text.lower().startswith(str(match["prefix"]).lower()):
            return False
        if "has_media" in match and bool(payload.get("has_media")) != bool(match["has_media"]):
            return False
        if "sender_id" in match and str(event.get("entity_id")) != str(match["sender_id"]):
            return False
        return True

    @staticmethod
    def _cooldown_key(rule: AutomationRule, event: dict[str, Any]) -> str:
        key = rule.match.get("cooldown_key")
        if key == "sender":
            return str(event.get("entity_id") or "unknown")
        return str(event.get("source_peer") or "global")

    @staticmethod
    def _telegram_target(peer: Any) -> Any:
        value = str(peer)
        return int(value) if value.lstrip("-").isdigit() else value

    def _row_to_rule(self, row: Any) -> AutomationRule:
        return AutomationRule(id=str(row["id"]), version=int(row["version"]), enabled=bool(row["enabled"]), owner=str(row["owner"]), trigger=self._load(row["trigger_json"]), scope=self._load(row["scope_json"]), match=self._load(row["match_json"]), actions=tuple(self._load(row["actions_json"])), cooldown_seconds=float(row["cooldown_seconds"]), max_runs=int(row["max_runs"]), created_at=float(row["created_at"]), updated_at=float(row["updated_at"]))

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False, default=str)

    @staticmethod
    def _load(value: str) -> Any:
        return json.loads(value)

    @staticmethod
    def _bound(value: dict[str, Any]) -> dict[str, Any]:
        raw = json.loads(json.dumps(value, default=str))
        encoded = json.dumps(raw, separators=(",", ":"), ensure_ascii=False)
        return json.loads(encoded[:MAX_ACTION_PAYLOAD]) if len(encoded.encode()) <= MAX_ACTION_PAYLOAD else {"event_id": str(value.get("event_id", "")), "event_type": str(value.get("event_type", "")), "source_peer": value.get("source_peer"), "message_id": value.get("message_id"), "entity_id": value.get("entity_id"), "payload": str(value.get("payload", ""))[:4000]}

    @staticmethod
    def _token(value: str, limit: int) -> str:
        value = value.strip()
        if not value or len(value) > limit:
            raise CommandError(f"Value must be 1-{limit} characters")
        return value

    @staticmethod
    def _run_id_for_job(_job: Job) -> str:
        return ""
