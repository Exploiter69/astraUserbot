# Program G — Automation Engine

**Status:** GREEN / COMPLETE
**Release target:** AstraUserbot 2.x
**Roadmap source:** `ROADMAP.md` → Program G
**Primary implementation:** `core/services/automation.py`
**Operator surface:** `plugins/automation.py`

## Outcome

Program G turns repeated Telegram work into durable, declarative rules backed by the existing JobEngine. Automation is not a second scheduler, workflow engine, Telegram transport, or authorization authority.

```text
Telegram/application observation
        ↓
Trigger
        ↓
WHERE scope + MATCH evaluation
        ↓
Cooldown / run-limit / dedupe
        ↓
Durable AUTOMATION_RUN job
        ↓
Typed ACTION execution
        ↓
TelegramFacade / existing service / JobEngine
        ↓
Durable step + audit state
```

## G1 — Rule model

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

Rule updates increment the persisted rule version. A queued job carries the rule version it was created against; stale versions are rejected instead of executing a changed contract.

## G2 — Trigger engine

Supported trigger vocabulary:

- `MESSAGE_NEW`
- `MESSAGE_EDIT`
- `MEDIA_OBSERVED`
- `SCHEDULED`
- `JOB_COMPLETED`
- `INTELLIGENCE_OBSERVED`
- `OWNER_COMMAND`

Telegram events arrive through the existing normalized `TelegramEventCollector`. The Automation Engine evaluates them without directly mutating Telegram state.

`JOB_COMPLETED` is bridged by a supervised plugin worker reading durable JobEngine events. The worker starts after the current event cursor so historical job completions are not unexpectedly replayed as new automation decisions.

`MEDIA_OBSERVED` and `INTELLIGENCE_OBSERVED` are supported as typed application triggers through the same engine API; producers can submit normalized observations without creating another event transport.

## G3 — Actions

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

`PLUGIN_ACTION` is inert until a plugin explicitly registers an approved action handler. There is no generic code execution escape hatch.

## G4 — Transactional workflows

A rule can contain multiple actions. Each run persists:

- `QUEUED`
- `RUNNING`
- per-step `STARTED`
- per-step `COMPLETED` / `FAILED`
- `RECOVERY_REQUIRED`
- final `COMPLETED`

The automation run has its own durable identity, while the actual worker lifecycle remains owned by JobEngine leases, retries and fencing.

Each action receives a deterministic idempotency key derived from run ID, step index and rule version. Completed steps are never re-executed during the same run.

When execution is interrupted, the automation run is marked `RECOVERY_REQUIRED`. Recovery does not invent a broader scope. External side effects remain subject to the JobEngine's existing uncertainty/reconciliation contract.

## Authorization and scope

Only the configured owner can create/update/enable/disable/delete/run automation rules.

Telegram-triggered rules require an explicit `chat_id` scope. Optional entity scope further narrows matching. Action targets are checked against the persisted rule scope.

Destructive/bulk automation is intentionally not exposed as an unrestricted action. Any future high-impact action must add its own deterministic target, authorization, rate, verification and audit contract.

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

The JSON creation surface is deliberate: it exposes the complete declarative rule contract without inventing a second natural-language rule parser. A future UX layer can compile friendly syntax into this same typed model.

Example:

```text
.autorule create hello {"trigger":{"type":"MESSAGE_NEW"},"scope":{"chat_id":123},"match":{"contains":"hello"},"actions":[{"type":"REPLY","text":"hello back"}],"cooldown_seconds":60}
```

## Existing productivity compatibility

Existing `.remind` and `.filter` features remain available. Program G does not silently rewrite them during this gate because they are existing Program E behavior with their own compatibility contract.

They are treated as migration candidates for a later convergence pass rather than duplicated inside the Automation Engine.

## Acceptance evidence

The repository contains dedicated Automation Engine contract tests covering:

- schema creation/versioning;
- owner-scoped rule creation;
- rule versioning;
- explicit scope validation;
- message matching;
- cooldown persistence;
- disabled rules;
- owner-command targeting;
- multi-step durable run state;
- stale-rule fencing;
- TelegramFacade reply execution;
- safe JobEngine delegation;
- explicit plugin-action registration;
- job-completion trigger support;
- arbitrary-code rejection;
- trigger-family declarations.

Production acceptance remains subject to local validation and the existing production acceptance gate. The implementation does not claim local test execution from this document.
