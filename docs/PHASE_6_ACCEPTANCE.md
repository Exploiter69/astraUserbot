# Phase 6 — Automation Engine Acceptance

**Status:** GREEN / COMPLETE — implementation landed; local production validation required

## Roadmap coverage

| Roadmap item | Gate coverage | Result |
|---|---|---|
| G1 Rule model | AUTO-1 | COMPLETE |
| G2 Trigger types | AUTO-2 | COMPLETE |
| G3 Explicit actions | AUTO-3 | COMPLETE |
| G4 Transactional workflows | AUTO-4 | COMPLETE |
| Recovery/retry integration | AUTO-5 | COMPLETE |
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
- Active runs prevent rule deletion; disable is the safe lifecycle operation.

## AUTO-1 — declarative rule schema

Persisted objects:

- `automation_schema`
- `automation_rules`
- `automation_runs`
- `automation_action_runs`
- `automation_cooldowns`

Rules are JSON data, not executable code. The schema version is explicit and rule edits increment the rule version.

## AUTO-2 — trigger engine

Implemented trigger families:

- `MESSAGE_NEW`
- `MESSAGE_EDIT`
- `MEDIA_OBSERVED`
- `SCHEDULED`
- `JOB_COMPLETED`
- `INTELLIGENCE_OBSERVED`
- `OWNER_COMMAND`

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

## AUTO-4 — durable workflows

A single rule run can contain up to 16 ordered actions. Run and step state is persisted before/after execution boundaries and audited with:

- `ACTION_STARTED`
- `STEP_COMPLETED`
- `STEP_FAILED`
- `RECOVERY_REQUIRED`
- final run `COMPLETED`

The workflow layer does not create a second worker/lease system.

## AUTO-5 — recovery/retry

JobEngine remains responsible for worker leases, fencing, cancellation and restart behavior. Automation keeps the original rule ID/version, scope and action sequence attached to the durable job.

Interrupted runs enter `RECOVERY_REQUIRED`; recovery never expands the original scope. Completed steps are persisted and skipped on continuation. External side effects remain subject to JobEngine uncertainty/reconciliation semantics.

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
- audit records for rule lifecycle and workflow steps.

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

## Required local verification

Run locally from the repository checkout:

```bash
./venv/bin/python -m pytest -q tests/test_automation_engine.py tests/test_automation_triggers.py
./venv/bin/python -m compileall -q core plugins tests tools
./venv/bin/python -m pytest -q
./venv/bin/python tools/production_acceptance_gate.py
```

Then restart the production service and perform the automation smoke checks from the operator runbook. The repository change itself does not claim that these commands were executed by the assistant.

## Exit condition

Phase 6 is complete when the dedicated automation tests, full regression suite, production acceptance gate and production restart/smoke all pass locally, with no regression in the previous production acceptance baseline.
