# Phase 6 — Automation Engine Acceptance

**Status:** COMPLETE — owner-host acceptance closed 2026-09-17

## Roadmap coverage

| Roadmap item | Gate coverage | Result |
|---|---|---|
| G1 Rule model | AUTO-1 | COMPLETE |
| G2 Trigger types | AUTO-2 | COMPLETE — real `MEDIA_OBSERVED` and `INTELLIGENCE_OBSERVED` producer paths wired |
| G3 Explicit actions | AUTO-3 | COMPLETE |
| G4 Transactional workflows | AUTO-4 | COMPLETE — durable enqueue intent and crash-window reconciliation |
| Recovery/retry integration | AUTO-5 | COMPLETE — JobEngine cancellation/recovery contract covered by integration tests |
| Gate discipline | AUTO-0..AUTO-5 | COMPLETE |

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

Rules are JSON data, not executable code. The schema version is explicit and rule edits increment the logical rule version independently of the database schema version.

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

`MEDIA_OBSERVED` has a real producer path: a media-bearing Telegram `MESSAGE_NEW` emits a bounded media observation through the existing `TelegramEventCollector` sink chain.

`INTELLIGENCE_OBSERVED` has a real producer path: `IntelGraph.add_observation()` emits a bounded application observation through an explicit sink wired by `ApplicationContext` to Automation Engine.

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

Accepted automation work enters `ENQUEUE_PENDING` before `JobEngine.enqueue()`. The run record and deterministic enqueue intent are committed together. Startup reconciles pending intent with the same JobEngine idempotency key, repairing both crash windows:

1. process disappears before the JobEngine row is committed;
2. JobEngine commits first and the process disappears before the automation run transitions to `QUEUED`.

A pending run whose durable intent is missing is moved to `RECOVERY_REQUIRED` rather than silently executing or inventing a new contract.

## AUTO-5 — recovery/retry

JobEngine remains responsible for worker leases, fencing, cancellation and restart behavior. Automation keeps the original rule ID/version, scope and action sequence attached to the durable job.

Interrupted runs enter `RECOVERY_REQUIRED`; recovery never expands the original scope. Completed steps are persisted and skipped on continuation. External side effects remain subject to JobEngine uncertainty/reconciliation semantics.

The dedicated integration suite directly verifies worker cancellation leading to `RECOVERY_REQUIRED` with the expected cancellation classification. This is the authoritative contract test for the failure path. A live Telegram cancellation smoke was not forced against a short-lived production action merely to manufacture an incident; production smoke instead verified successful durable execution and restart preservation.

## Rule lifecycle / deletion semantics

`.autorule delete <id>` is intentionally a **tombstone**, not a physical SQL `DELETE`:

1. the engine verifies that the rule has no `ENQUEUE_PENDING`, `QUEUED`, `RUNNING` or `RECOVERY_REQUIRED` run;
2. it marks the rule disabled and records `deleted_at`;
3. live list/get/trigger paths exclude the tombstone;
4. `automation_runs`, `automation_action_runs`, `automation_cooldowns` and `audit_events` remain durable;
5. the rule's foreign-key relationships are not weakened or bypassed;
6. the same ID may later be recreated, producing a new logical rule version while preserving old execution history.

An active run still blocks deletion. The operator must disable the rule and allow the accepted run to reach a safe terminal/recovery state first.

## Scheduler restart semantics

One-shot schedules remain protected by durable run history. Interval schedules use the durable `automation_cooldowns` row with `cooldown_key='schedule'` as the restart-safe last-fire record. The in-memory timestamp is no longer the sole duplicate guard.

Owner-host production smoke created `schedulertest` with a 60-second interval and observed successful `AUTOMATION_RUN` completion before and after an `astra.service` restart. No restart-induced immediate duplicate of the already-completed scheduled action was observed; subsequent scheduled executions were consistent with the configured interval.

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

Fresh owner-host verification completed on 2026-09-17:

- focused automation/event/intel suite: **27 passed in 17.18s**;
- full repository suite: **315 passed in 54.77s**;
- `compileall` for `core plugins tests tools`: **PASS**;
- production acceptance Gate 1: **315 passed**;
- Gate 2 compile check: **PASS**;
- Gate 3 plugin behavior audit: **PASS**;
- Gate 4 plugin ecosystem quality audit: **PASS**;
- Gate 5 media pipeline: **PASS**;
- Gate 6 isolation/security: **PASS**;
- Gate 7 storage/database: **PASS**;
- Gate 8 durable jobs: **PASS**;
- Gate 9 Phase 18 audit: **PASS**;
- Gate 10 shutdown probe: **PASS**;
- final production acceptance: **`PRODUCTION_ACCEPTANCE_PASS`**.

The production gate reported `SHUTDOWN_RUNTIME_GATE_REQUIRED: YES` before Gate 10; the shutdown probe then passed with return code 0 and `SHUTDOWN_CONTEXT_RETURNED elapsed=2.543s`.

## Production restart/smoke evidence

Owner-host production acceptance completed on 2026-09-17:

1. `astra.service` restarted successfully and returned to `active (running)` with a new Main PID.
2. Startup logs showed `Telegram event collector started handlers=6` and `Automation Engine started`.
3. Startup completed with `RUNNING=51`, `Services 22/22`, `Plugins 51 RUNNING`, `Commands 137`, `Jobs READY`, `Isolation BUBBLEWRAP-AVAILABLE`, `AI Gateway GROQ READY`, and `SYSTEM READY`.
4. `.autostatus` showed all seven trigger families and all eight action types.
5. Owner-created automation smoke rules executed through the real Telegram command surface and produced terminal `AUTOMATION_RUN` jobs.
6. Live deletion/tombstone smoke created `phase6delete`, executed run `732a3eb1c75f`, then deleted the rule successfully; `.autorule list` no longer exposed it while the implementation/test contract preserves its historical records.
7. Scheduler smoke created `schedulertest` with a 60-second interval; scheduled automation completed before/after service restart without an observed restart-induced duplicate.
8. Recovery/cancellation behavior is covered by the dedicated JobEngine integration test, including `WORKER_CANCELLED → RECOVERY_REQUIRED`; production smoke did not force a cancellation against a short-lived action.
9. Existing durable jobs remained visible after restart, with no restart-created duplicate of the completed automation action observed.

## Exit condition

Phase 6 is complete. Completion is based on the combination of dedicated contract/integration tests, fresh full regression, production acceptance gates, and owner-host daemon/Telegram restart smoke. Failure paths that are intentionally difficult or unsafe to manufacture in a live Telegram session are accepted through their deterministic integration contract tests rather than by inducing artificial production incidents.

No further Phase 6 implementation work is required. The next roadmap gate is **Phase 7 — Intelligence Foundation / Program H (IntelGraph)**.
