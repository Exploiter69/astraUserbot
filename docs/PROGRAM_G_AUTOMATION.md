# Program G — Automation Engine

**Status:** COMPLETE — owner-host acceptance closed 2026-09-17  
**Release target:** AstraUserbot 2.x  
**Roadmap source:** `ROADMAP.md` → Program G  
**Primary implementation:** `core/services/automation.py`  
**Operator surface:** `plugins/automation.py`

## Outcome

Program G turns repeated Telegram/application work into durable, declarative rules backed by the existing JobEngine. Automation is not a second scheduler, workflow engine, Telegram transport, or authorization authority.

```text
Telegram/application observation
        ↓
Trigger
        ↓
WHERE scope + MATCH evaluation
        ↓
Cooldown / run-limit / dedupe
        ↓
Durable AUTOMATION_RUN acceptance intent
        ↓
JobEngine durable job
        ↓
Typed ACTION execution
        ↓
TelegramFacade / existing service / JobEngine
        ↓
Durable step + audit state
```

## G1 — Rule model — COMPLETE

Rules are persisted in SQLite using a versioned automation schema.

Each rule contains:

- stable ID;
- schema/version;
- enabled state;
- owner;
- `WHEN` trigger;
- explicit `WHERE` scope;
- declarative `MATCH` conditions;
- one to sixteen typed actions;
- cooldown;
- maximum run count;
- created/updated timestamps.

Rules never contain executable Python or arbitrary expressions.

Rule updates increment the persisted logical rule version. A queued job carries the rule version it was created against; stale versions are rejected instead of executing a changed contract. Database schema versioning is independent of logical rule versioning.

Schema version 2 adds nullable `automation_rules.deleted_at`. Deletion is a durable tombstone, preserving foreign-key integrity and historical execution records.

## G2 — Trigger engine — COMPLETE

Supported trigger vocabulary:

- `MESSAGE_NEW`
- `MESSAGE_EDIT`
- `MEDIA_OBSERVED`
- `SCHEDULED`
- `JOB_COMPLETED`
- `INTELLIGENCE_OBSERVED`
- `OWNER_COMMAND`

Telegram events arrive through the existing normalized `TelegramEventCollector`. A new Telegram message carrying media emits both the normal `MESSAGE_NEW` observation and a bounded `MEDIA_OBSERVED` observation through the same collector/sink path.

`JOB_COMPLETED` is bridged by a supervised plugin worker reading durable JobEngine events. The worker starts after the current event cursor so historical job completions are not unexpectedly replayed as new automation decisions.

`INTELLIGENCE_OBSERVED` is produced by `IntelGraph.add_observation()` through an explicit observation sink wired by `ApplicationContext`. No second event transport is introduced.

Schedule rules require an explicit epoch anchor and positive interval. Interval duplicate protection uses durable scheduler state.

## G3 — Actions — COMPLETE

Supported typed actions:

- `REPLY`
- `FORWARD`
- `TAG`
- `INDEX`
- `ARCHIVE`
- `NOTIFY_OWNER`
- `PLUGIN_ACTION`
- `START_JOB`

Rules cannot broaden their own scope. Telegram writes are routed through `TelegramFacade`'s governed transport path. Durable work is delegated to the existing JobEngine.

`TAG` and `INDEX` remain bounded audit/index observations in this gate; they do not create a separate unbounded data store.

`PLUGIN_ACTION` is inert until a plugin explicitly registers an approved action handler. There is no generic code execution escape hatch.

`START_JOB` only accepts an already-registered JobEngine handler and cannot target `AUTOMATION_RUN`, preventing recursive construction of a second workflow system.

## G4 — Transactional workflows — COMPLETE

A rule can contain multiple actions. Each run persists:

- `ENQUEUE_PENDING`
- `QUEUED`
- `RUNNING`
- per-step `STARTED`
- per-step `COMPLETED` / `FAILED`
- `RECOVERY_REQUIRED`
- final `COMPLETED`

The automation run has its own durable identity, while the actual worker lifecycle remains owned by JobEngine leases, retries and fencing.

### Durable enqueue acceptance

The trigger-to-JobEngine handoff uses a durable `ENQUEUE_PENDING` intent before calling `JobEngine.enqueue()`. The run and bounded enqueue intent are committed together. Startup reconciles pending intent using the same deterministic JobEngine idempotency key.

This closes both relevant crash windows:

1. process disappears before the JobEngine row is committed;
2. JobEngine commits first and the process disappears before the automation run transitions to `QUEUED`.

Each action receives a deterministic idempotency key derived from run ID, step index and rule version. Completed steps are never re-executed during the same run.

## G5 — Recovery/retry integration — COMPLETE

JobEngine remains responsible for worker leases, fencing, cancellation and restart behavior. Automation keeps the original rule ID/version, scope and action sequence attached to the durable job.

Interrupted runs enter `RECOVERY_REQUIRED`; recovery never expands the original scope. Completed steps are persisted and skipped on continuation. External side effects remain subject to the JobEngine uncertainty/reconciliation contract.

The dedicated JobEngine integration suite verifies worker cancellation → `RECOVERY_REQUIRED` with the expected `WORKER_CANCELLED` classification. This is the authoritative failure-path contract. A live Telegram cancellation was not artificially forced against a short-lived production action.

## Scheduler durability — COMPLETE

Scheduled automation remains a supervised lifecycle task. One-shot schedules are protected by durable run history. Interval schedules use the durable `automation_cooldowns` record with `cooldown_key='schedule'` rather than an in-memory timestamp alone, so a process restart does not reset the interval guard.

Owner-host smoke created `schedulertest` with:

- `type=SCHEDULED`;
- `interval_seconds=60`;
- `max_runs=3`;
- bounded `TAG` action.

The schedule executed successfully and continued across an `astra.service` restart without an observed restart-induced immediate duplicate.

## Rule lifecycle / tombstone deletion — COMPLETE

`.autorule delete <id>` is a tombstone, not a physical SQL delete.

The engine:

1. rejects deletion while runs are `ENQUEUE_PENDING`, `QUEUED`, `RUNNING` or `RECOVERY_REQUIRED`;
2. disables the rule and records `deleted_at`;
3. removes the rule from live list/get/trigger paths;
4. preserves `automation_runs`, `automation_action_runs`, `automation_cooldowns` and `audit_events`;
5. preserves foreign-key enforcement;
6. permits later recreation under the same rule ID with a new logical rule version.

Owner-host smoke created and executed `phase6delete` (`AUTOMATION_RUN` `732a3eb1c75f`), deleted it successfully, and confirmed it disappeared from the live rule list. Automated tombstone tests cover preservation of historical execution/audit records.

## Authorization and scope

Only the configured owner can create/update/enable/disable/delete/run automation rules.

Telegram-triggered rules require an explicit `chat_id` scope. Optional entity scope further narrows matching. Action targets are checked against the persisted rule scope.

Destructive/bulk automation is intentionally not exposed as an unrestricted action. Future high-impact actions must add their own deterministic target, authorization, rate, verification and audit contract.

## Bounds

- maximum rules: 1000;
- maximum actions per rule: 16;
- maximum action payload: 64 KiB;
- maximum Telegram match text considered: 4096 characters;
- maximum trigger evaluation burst: 32 rules per observation;
- cooldown: 0–7 days;
- maximum rule runs: 100,000;
- archive action limit: 100 messages per delegated archive job.

The underlying JobEngine continues to enforce its payload/result, worker, lease and resource limits.

## Operator commands

```text
.autorule list
.autorule show <id>
.autorule create <id> <json-rule>
.autorule enable <id>
.autorule disable <id>
.autorule delete <id>
.autorule run <id>
.autostatus
```

The JSON creation surface deliberately exposes the complete declarative rule contract without inventing a second natural-language rule parser. A future UX layer can compile friendly syntax into this same typed model.

## Existing productivity compatibility

Existing `.remind` and `.filter` features remain available. Program G does not silently rewrite them because they are existing Program E behavior with their own compatibility contract.

## Acceptance evidence

Fresh owner-host verification completed on 2026-09-17:

- focused automation/event/intel suite: **27 passed in 17.18s**;
- full repository suite: **315 passed in 54.77s**;
- `compileall -q core plugins tests tools`: **PASS**;
- production acceptance Gates 1–10: **PASS**;
- final production acceptance: **`PRODUCTION_ACCEPTANCE_PASS`**.

Production Gate 10 shutdown probe returned code 0 with `SHUTDOWN_CONTEXT_RETURNED elapsed=2.543s`.

Owner-host daemon/Telegram smoke also verified:

- successful service restart with a new Main PID;
- `Telegram event collector started handlers=6`;
- `Automation Engine started`;
- `RUNNING=51`;
- `Services 22/22`;
- `Plugins 51 RUNNING`;
- `Commands 137`;
- `Jobs READY`;
- `Isolation BUBBLEWRAP-AVAILABLE`;
- `AI Gateway GROQ READY`;
- `SYSTEM READY`;
- seven trigger families visible through `.autostatus`;
- eight action types visible through `.autostatus`;
- successful owner-triggered durable automation jobs;
- successful tombstone deletion smoke;
- successful scheduler restart smoke;
- durable jobs retained across restart.

## Final decision

**Program G / Phase 6 is closed.** No further Phase 6 implementation or acceptance work is required.

The next gate is **Phase 7 — Intelligence Foundation / Program H (IntelGraph)**. Before implementation, perform the Program H prerequisite/design gate from `ROADMAP.md`: confirm the existing observation/event concepts, source/provenance schema, canonical entity model, storage boundaries, evidence/confidence semantics, and the dependency order before adding new intelligence sources.
