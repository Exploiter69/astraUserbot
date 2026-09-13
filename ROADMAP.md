# AstraUserbot — Canonical Roadmap

**Status:** Platform implementation complete; release engineering / production acceptance is the current focus.  
**Version:** 3.0  
**Current release:** 1.0.0 candidate  
**Cost target:** ₹0 / $0

> This file is the execution plan. Architecture belongs in `ARCHITECTURE.md`; durable contracts belong in `DATA_MODEL.md`, `JOB_MODEL.md`, `SAFETY_CONTRACT.md` and `PRODUCTION_BOUNDARY.md`.

## Non-negotiable rules

```text
Protect working behavior.
Do not mass-rewrite plugins without evidence.
Do not introduce paid infrastructure.
Do not treat in-memory tasks as durable.
Do not let AI become authority.
Do not let caches become source-of-truth.
Do not hide plugin/task/job failures.
Do not bypass authorization.
Do not allow unbounded resource use.
Do not claim verification when only execution succeeded.
```

## Phase status

| Phase | Area | Status |
|---|---|---|
| 0 | Baseline/protection | COMPLETE |
| 1 | Plugin/command foundation | COMPLETE |
| 2 | Shared runtime services | COMPLETE |
| 3 | Cache foundation | COMPLETE |
| 4 | Storage/migrations | COMPLETE |
| 5 | Durable JobEngine | COMPLETE |
| 6 | P0 reliability/security fixes | COMPLETE |
| 7 | Media platform | COMPLETE |
| 8 | AI Gateway | COMPLETE |
| 9 | Plugin migration | COMPLETE / VERIFIED |
| 10 | Search & knowledge | COMPLETE / VERIFIED |
| 11 | Observability | COMPLETE / VERIFIED |
| 12 | Feature expansion foundation | COMPLETE / VERIFIED |
| 13 | Performance/metrics | COMPLETE / VERIFIED |
| 14 | Real selective isolation | COMPLETE / VERIFIED |
| 15 | Platform maturity | COMPLETE / VERIFIED |
| 16–18 | Ecosystem, shutdown, jobs/operator hardening | COMPLETE / VERIFIED |
| Release | Documentation/recovery/acceptance | IN PROGRESS |

## Completed platform work

The current main branch contains the service-oriented modular monolith foundation, deterministic plugin lifecycle, command ownership, bounded task supervision, shared HTTP/subprocess/media/AI services, SQLite WAL/migrations, durable jobs with leases/fencing/`UNCERTAIN` recovery, real Bubblewrap isolation for classified workloads, FTS5 search, operator diagnostics, plugin behavior/ecosystem audits, backup/restore integrity checks and release tooling.

The active ecosystem is **41 plugins running with 4 intentionally quarantined legacy AI modules**. The four quarantined modules are not release blockers and must not be reactivated without a reviewed gateway-compatible migration.

## Current release-engineering block

### Documentation synchronization — COMPLETE

Canonical architecture and operational contracts now describe the implemented runtime rather than historical future-state plans.

### Production invariants — COMPLETE

Invariants are consolidated across architecture, safety, production boundary, job, storage, media, AI, isolation and compatibility documents.

### Operator runbook — COMPLETE

`OPERATIONS_RUNBOOK.md` documents normal startup, triage, health, plugin/job operations, logs, resource pressure and emergency stop.

### Recovery runbook — COMPLETE

`DISASTER_RECOVERY.md` documents evidence preservation, verified backups, restore, uncertain-job reconciliation, cache/search recovery, credential compromise and rollback.

### Upgrade procedure — COMPLETE

`UPGRADE_PROCEDURE.md` documents pre-flight backup, source verification, acceptance gate, restart, smoke tests and rollback.

### Failure-mode matrix — COMPLETE

`FAILURE_MODE_MATRIX.md` maps common failures to detection, safe state, operator response and prohibited actions.

### Release checklist — COMPLETE

`RELEASE_CHECKLIST.md` is the release artifact checklist and blocker list.

### Production acceptance gate — IMPLEMENTED

`PRODUCTION_ACCEPTANCE.md` defines automated and manual acceptance. `tools/production_acceptance_gate.py` executes the non-destructive automated contract.

## Release sequence

```text
DOCUMENT
   ↓
RUN AUTOMATED ACCEPTANCE
   ↓
CREATE VERIFIED BACKUP
   ↓
MANUAL PRODUCTION ACCEPTANCE
   ↓
CONTROLLED RESTART
   ↓
OWNER SMOKE TEST
   ↓
RECORD ACCEPTANCE
   ↓
CREATE v1.0.0 TAG
   ↓
OBSERVE
```

The tag is created only after the acceptance gate passes. The repository contains `VERSION=1.0.0` for this release candidate.

## Post-release roadmap

After 1.0.0 is accepted, feature work resumes only from measured requirements. Candidate areas include useful Telegram utilities, productivity/automation, media, web/feed tools, developer utilities and AI features. New features must consume existing service contracts and add regression coverage.

Performance tuning remains evidence-driven. New infrastructure requires proof that the existing single-process/SQLite design cannot satisfy the requirement.

## Global Definition of Done

Astra is platform-mature when:

1. lifecycle and ownership are observable;
2. command conflicts cannot hide;
3. long-lived tasks are bounded and supervised;
4. durable work survives restart with explicit uncertainty semantics;
5. shared infrastructure is reused;
6. cache/search are bounded and rebuildable;
7. persistence is migration-driven and recoverable;
8. high-risk features have regression/security coverage;
9. AI is provider-independent, bounded and advisory;
10. diagnostics expose real health without secrets;
11. resource use is bounded;
12. recovery and rollback are documented;
13. release acceptance is executable;
14. the platform remains ₹0/$0.

> **Build the platform once. Make every later plugin cheaper, safer, and faster to build.**
