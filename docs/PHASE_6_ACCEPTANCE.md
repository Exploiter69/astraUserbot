# Phase 6 — Automation Engine Acceptance

**Status:** IMPLEMENTATION HARDENED — fresh local regression and production acceptance required

## Roadmap coverage

| Roadmap item | Gate coverage | Result |
|---|---|---|
| G1 Rule model | AUTO-1 | COMPLETE |
| G2 Trigger types | AUTO-2 | COMPLETE after real producer wiring |
| G3 Explicit actions | AUTO-3 | COMPLETE |
| G4 Transactional workflows | AUTO-4 | COMPLETE after durable enqueue-intent hardening |
| Recovery/retry integration | AUTO-5 | COMPLETE |
| Gate discipline | AUTO-0..AUTO-5 | Implementation complete; local evidence pending |

## AUTO-0 — prerequisites

- JobEngine remains the only durable work engine.
- TelegramFacade remains the normal governed Telegram mutation boundary.
- Automation is an ApplicationContext service.
- Event input is the existing normalized Telegram event envelope.
- Long-lived automation workers are supervised.
- Rules are owner-controlled.
- Scope is explicit and cannot be widened by a worker.
- Idempotency keys are deterministic at rule/run/step boundaries.
- Rule versions fence queued work from changed definitions.
- Disabled rules stop new triggers; already accepted jobs retain their persisted rule contract.
- Active runs prevent rule deletion; disable is the safe lifecycle operation while those runs remain active.
- Deleting an inactive rule is a durable tombstone operation: the rule leaves the live control surface while historical runs, action records and audit records remain intact.

## AUTO-1 — declarative rule schema

Persisted objects:

- `automation_schema`
- `automation_rules`
- `automation_runs`
- `automation_action_runs`
- `automation_cooldowns`

Rules are JSON data, not executable code. The schema version is explicit and rule edits increment the rule version.

Schema version 2 adds nullable `automation_rules.deleted_at`. This is a tombstone rather than a physical delete, because historical `automation_runs` retain their foreign-key reference to the rule. Foreign-key enforcement remains intact and historical execution records are never cascaded away.

Live rule queries filter `deleted_at IS NULL`. A deleted rule is therefore absent from `.autorule list`, cannot be fetched or triggered as a live rule, and can safely be recreated later under the same rule ID without destroying prior history.

## AUTO-2 — trigger engine

Implemented trigger families:

- `MESSAGE_NEW`
- `MESSAGE_EDIT`
- `MEDIA_OBSERVED`
- `SCHEDULED`
- `JOB_COMPLETED`
- `INTELLIGENCE_OBSERVED`
- `OWNER_COMMAND`

`MEDIA_OBSERVED` now has a real producer path: a media-bearing Telegram `MESSAGE_NEW` emits a bounded media observation through the existing `TelegramEventCollector` sink chain.

`INTELLIGENCE_OBSERVED` now has a real producer path: `IntelGraph.add_observation()` emits a bounded application observation through an explicit sink wired by `ApplicationContext` to Automation Engine.

Matching is deterministic and bounded. Telegram message rules require chat scope. Schedule rules require an explicit epoch timestamp. Job completion is bridged from durable JobEngine events by a supervised worker.

## AUTO-3 — action authorization

Implemented action vocabulary:

- `REPLY`
- `FORWARD`
- `TAG`
- `INDEX`
- `ARCHIVE`
- `NOTIFY_OWNER`
- `PLUGIN_ACTION`
- `START_JOB`

No arbitrary Python, shell, URL callback or tool execution is accepted as an action. Plugin actions require explicit handler registration. Durable work delegates to JobEngine. Telegram operations use the governed facade path.

`TAG` / `INDEX` are intentionally bounded audit/index observations in this gate rather than an unbounded secondary data store.

`START_JOB` requires an existing registered JobEngine handler and rejects `AUTOMATION_RUN`, preventing recursive construction of a second workflow system.

## AUTO-4 — durable workflows

A single rule run can contain up to 16 ordered actions. Run and step state is persisted before/after execution boundaries and audited with:

- `ACTION_STARTED`
- `STEP_COMPLETED`
- `STEP_FAILED`
- `RECOVERY_REQUIRED`
- final run `COMPLETED`

The workflow layer does not create a second worker/lease system.

### Trigger → JobEngine consistency

Accepted automation work now enters `ENQUEUE_PENDING` before `JobEngine.enqueue()`. The run record and deterministic enqueue intent are committed together. Startup reconciles any pending intent with the same JobEngine idempotency key, repairing both crash windows:

1. process disappears before the JobEngine row is committed;
2. JobEngine commits first and the process disappears before the automation run transitions to `QUEUED`.

A pending run whose durable intent is missing is moved to `RECOVERY_REQUIRED` rather than silently executing or inventing a new contract.

## AUTO-5 — recovery/retry

JobEngine remains responsible for worker leases, fencing, cancellation and restart behavior. Automation keeps the original rule ID/version, scope and action sequence attached to the durable job.

Interrupted runs enter `RECOVERY_REQUIRED`; recovery never expands the original scope. Completed steps are persisted and skipped on continuation. External side effects remain subject to JobEngine uncertainty/reconciliation semantics.

## Rule lifecycle / deletion semantics

`.autorule delete <id>` is intentionally a **tombstone**, not a physical SQL `DELETE`:

1. the engine verifies that the rule has no `ENQUEUE_PENDING`, `QUEUED`, `RUNNING` or `RECOVERY_REQUIRED` run;
2. it marks the rule disabled and records `deleted_at`;
3. live list/get/trigger paths exclude the tombstone;
4. `automation_runs`, `automation_action_runs`, `automation_cooldowns` and `audit_events` remain durable;
5. the rule's foreign-key relationships are not weakened or bypassed;
6. the same ID may later be recreated, producing a new rule version while preserving the old execution history.

An active run still blocks deletion. The operator must disable the rule and allow the accepted run to reach a safe terminal/recovery state first. This preserves the original durable rule contract rather than deleting an object still referenced by work in flight.

## Scheduler restart semantics

One-shot schedules remain protected by durable run history. Interval schedules now use the durable `automation_cooldowns` row with `cooldown_key='schedule'` as the restart-safe last-fire record. The in-memory timestamp is no longer the sole duplicate guard.

## Resource/cancellation/failure controls

- bounded rule count;
- bounded action count;
- bounded rule/match/action payloads;
- bounded trigger evaluation;
- bounded archive delegation;
- explicit cooldowns and max-run limits;
- supervised scheduler and job-completion bridge;
- cancellation propagates into automation execution;
- controlled `JobError` classification for stale/missing/failed automation contracts;
- audit records for rule lifecycle, enqueue acceptance and workflow steps.

## Security/safety controls

- owner-only rule lifecycle;
- explicit Telegram chat scope;
- no arbitrary code execution;
- no scope expansion from action payloads;
- no second Telegram transport;
- no second durable workflow engine;
- no secrets in rule payloads by design;
- destructive/bulk actions require future explicit policy rather than inheriting unrestricted power.

## Existing product compatibility

Program E productivity commands `.remind` and `.filter` remain intact. They are not duplicated or silently migrated in Phase 6. Convergence can be performed later as an explicit compatibility change.

## Automated verification evidence

The previous owner-host full regression baseline was:

- `303 passed in 80.29s`
- 0 failures

That baseline predates the latest Phase 6 acceptance-hardening changes. New focused tests were added for durable enqueue reconciliation, scheduler durability, `MEDIA_OBSERVED`, `INTELLIGENCE_OBSERVED` producer paths, and rule tombstone deletion/history preservation. The full suite must be rerun locally after these changes.

## Required local verification

Run locally from the repository checkout:

```bash
.venv/bin/python -m pytest -q tests/test_automation_engine.py tests/test_automation_triggers.py tests/test_automation_jobengine_integration.py tests/test_automation_durability.py tests/test_telegram_events.py tests/test_intelgraph.py
.venv/bin/python -m compileall -q core plugins tests tools
.venv/bin/python -m pytest -q
.venv/bin/python tools/production_acceptance_gate.py
```

Then restart the production service and perform the automation smoke checks from the operator runbook. The repository change itself does not claim that these commands were executed by the assistant.

### Production restart/smoke acceptance

The remaining owner-host evidence must prove the real daemon lifecycle, not merely unit-test behavior:

1. restart `astra.service` successfully;
2. confirm the service returns to `active (running)` with a new process;
3. confirm Automation Engine startup is present in the service log;
4. create an owner-controlled bounded automation rule;
5. trigger it through the real Telegram/plugin surface;
6. confirm the resulting `AUTOMATION_RUN` exists in JobEngine and reaches its terminal state;
7. confirm the automation run/step audit records are durable;
8. exercise a bounded cancellation/recovery path and confirm `RECOVERY_REQUIRED` is preserved;
9. after restart, confirm previously durable automation state remains present and no completed action is duplicated;
10. verify an interval schedule does not immediately duplicate its previous execution after restart;
11. delete the now-inactive smoke-test rule and confirm it disappears from the live rule list while its completed automation history remains queryable in SQLite.

## Exit condition

Phase 6 is complete when the dedicated automation tests, real JobEngine integration tests, fresh full regression suite, production acceptance gate and production restart/smoke all pass locally, with no regression in the previous production acceptance baseline.