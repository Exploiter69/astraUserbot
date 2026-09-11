# AstraUserbot — Detailed Canonical Roadmap

**Status:** Canonical implementation sequence  
**Version:** 2.5  
**Cost target:** ₹0 / $0

> This file is the execution plan. Architectural changes belong in `DECISIONS.md`; contracts are defined in `ARCHITECTURE.md`, `DATA_MODEL.md`, `JOB_MODEL.md`, `SAFETY_CONTRACT.md`, and `PRODUCTION_BOUNDARY.md`.

## 0. Non-Negotiable Rules

```text
Do not destroy working behavior without evidence.
Do not mass-rewrite plugins before platform services exist.
Do not introduce paid infrastructure.
Do not treat asyncio tasks as durable jobs.
Do not let AI become authority.
Do not let caches become source-of-truth.
Do not hide plugin/task/job failures.
Do not bypass authorization for convenience.
Do not allow unbounded resource consumption.
Do not claim verification when only execution succeeded.
```

---

# Phase 0 — Baseline & Protection — COMPLETE

### Deliverables

- Git/GitHub baseline;
- secret/session protection;
- dependency inventory;
- plugin inventory;
- source-level plugin audit;
- architecture specification;
- data/job/safety/boundary contracts.

### Exit

Baseline commit exists, runtime secrets are excluded, existing plugin behavior is understood, and confirmed defects are recorded.

---

# Phase 1 — Plugin & Command Foundation — COMPLETE

**Goal:** make startup, plugin lifecycle, registration, and command execution deterministic.

## 1.1 Plugin Manager — COMPLETE

Implemented:

```text
DISCOVERED
LOADED
RUNNING
FAILED_IMPORT
FAILED_SETUP
DISABLED
UNLOADED
```

Requirements completed:

- deterministic discovery;
- metadata validation;
- dependency graph;
- cycle detection;
- ownership tracking;
- setup/shutdown isolation;
- registration cleanup;
- startup report;
- compatibility adapter for legacy `setup()` plugins.

## 1.2 Command Router — COMPLETE

Implemented:

- canonical names;
- aliases;
- duplicate detection;
- plugin ownership;
- permission metadata;
- side-effect metadata support;
- correlation IDs;
- safe error boundary.

The real ACL/PMGuard `.block`/`.unblock` conflict was resolved by making ACL the sole owner; PMGuard no longer registers duplicate handlers.

## 1.3 Safe Errors — COMPLETE

Implemented structured error classes, stable error codes, bounded user-facing messages, correlation context, and safe unexpected-exception handling.

## 1.4 TaskSupervisor — COMPLETE

Implemented centralized supervision for ephemeral long-lived tasks with owner/name/lifecycle tracking, cancellation, bounded history, failure classification and graceful shutdown.

### Gate 1 — PASS

**28/28 tests passed and compile validation passed.**

---

# Phase 2 — Shared Runtime Services — COMPLETE

**Goal:** extract duplicated infrastructure into explicit, reusable process-wide services.

Current core services include:

```text
HttpService
SubprocessService
TelegramFacade
WorkspaceService
MediaService
AIService
```

### Gate 2 — PASS

**Phase 2 service regression suite passed.**

---

# Phase 3 — Cache Foundation — COMPLETE

**Goal:** establish the reusable cache before broad plugin migration.

### Gate 3 — PASS

**49/49 full regression tests passed.**

---

# Phase 4 — Storage & Migration Foundation — COMPLETE

**Goal:** create durable shared platform persistence.

### Gate 4 — PASS

**Deterministic platform storage/migration validation is complete.**

---

# Phase 5 — Durable Job Engine — COMPLETE

**Goal:** make restart-sensitive work durable.

### Gate 5 — PASS

**Uncertain external outcomes require explicit reconciliation before replay.**

---

# Phase 6 — Confirmed P0 Reliability Fixes — COMPLETE

**Goal:** repair high-risk existing features before expansion.

Completed:

1. ACL/PMGuard duplicate commands.
2. Advertised admin `demote` and `slow` semantics.
3. SecretStore migration from base64 obfuscation to authenticated encryption.
4. Serialized/bounded eval output capture.
5. Account-archiver error visibility and retention.
6. Persistent bounded logger message cache.
7. PMGuard contact refresh.
8. AFK sender cooldown.
9. Isolated stream outputs.
10. Media cleanup normalization.
11. Shared subprocess boundary for rclone/aria2.
12. Explicit uncertain-job recovery coverage.

### Gate 6 — PASS

**73 tests passed and compile validation passed.**

---

# Phase 7 — Media Platform — COMPLETE

**Goal:** make media a reusable, bounded, isolated service.

### Gate 7 — PASS

**81/81 tests passed, 0 failures, 0 errors, and compile validation passed.**

---

# Phase 8 — AI Gateway — COMPLETE

**Goal:** remove provider lock-in while preserving existing AI command behavior.**

### Gate 8 — PASS

**Phase 8 implementation and contract tests are complete.** The active command path is provider-independent; legacy provider-specific modules remain quarantined compatibility artifacts.

---

# Phase 9 — Plugin Migration Program — IMPLEMENTATION COMPLETE

**Goal:** move the existing ecosystem onto platform services.**

Phase 9 is the migration pass that turns the platform work from Phases 1–8 into the actual existing-plugin ecosystem.

## Batch A — Security/Admin — COMPLETE

ACL, PMGuard, logger, account archiver, vault, eval and admin reliability fixes were completed in Phase 6 and retained as the Phase 9 migration baseline.

## Batch B — Network/OSINT — COMPLETE

Migrated:

```text
plugins/network_osint/dns.py
plugins/network_osint/headers.py
plugins/network_osint/ipinfo.py
plugins/network_osint/speedtest.py
plugins/advanced/osint_recon.py
```

HTTP consumers now resolve `HttpService` from `ApplicationContext`. Speedtest uses `SubprocessService` with bounded output and timeout policy. DNS record types are explicitly validated and query parameters are encoded by the shared HTTP layer.

## Batch C — Media — COMPLETE

Media consumers were migrated through the Phase 7 `MediaService` boundary:

```text
media/ffmpeg.py
advanced/mediaflow.py
media_ops/video.py
media_ops/speech.py
media_ops/stream.py
media/aria2.py
media/rclone.py
```

OCR was additionally migrated to the canonical `WorkspaceService` + `SubprocessService` boundary during Phase 9.

## Batch D — System/Automation — COMPLETE

Shared-infrastructure consumers now use platform services. In particular:

```text
plugins/system/sysinfo.py
plugins/backup/cloud_backup.py
plugins/media/ocr.py
plugins/network_osint/speedtest.py
```

No active plugin invokes the legacy `helpers.shell` boundary.

## Batch E — AI/Advanced — COMPLETE

The active `.ask`, `.summarize`, and `.transcribe` command path was migrated through `AIService` in Phase 8. The old Groq-specific command modules remain quarantined compatibility artifacts and are not part of active command ownership.

The advanced OSINT recon consumer was migrated to `HttpService` during Phase 9.

## Every migration must

1. preserve intended behavior;
2. add regression coverage;
3. use shared service contracts;
4. remove duplicate infrastructure;
5. verify cleanup/failure behavior;
6. update documentation;
7. run startup/command smoke tests.

## Phase 9 Gate

`PHASE_9_READINESS.md` defines the migration contract and `tests/test_phase9_gate.py` provides the phase-specific static regression gate.

**Implementation is complete. Gate 9 is pending local full-suite validation.** Do not mark Phase 9 PASS until the local full suite and Phase 9 gate pass together.

---

# Phase 10 — Search & Knowledge

Start with SQLite indexes and FTS5.

Sources:

```text
plugin metadata
commands
notes
message cache
documents
OCR
transcripts
```

Later, semantic/vector retrieval may be added only if measurable value exists.

### Gate 10

Indexes can be rebuilt from authoritative source records.

---

# Phase 11 — Observability

Implement:

```text
!health
!plugins
!tasks
!jobs
!cache
!stats
!diagnostics
```

Diagnostics cover plugin state, conflicts, tasks, jobs, cache, DB, HTTP, resources, and recent classified errors without secrets.

### Gate 11

The owner can diagnose the majority of runtime failures without opening source code first.

---

# Phase 12 — Feature Expansion

Only after the platform gates pass, add broad capability families:

- Telegram utilities;
- messaging/productivity;
- reminders/scheduling;
- bulk tools;
- media;
- downloads/uploads;
- feeds/RSS;
- web utilities;
- developer tools;
- Linux/system tools;
- search/knowledge;
- backup/export;
- AI utilities;
- social/fun modules.

Every feature consumes existing platform services.

---

# Phase 13 — Performance

Measure before tuning:

```text
command latency
handler latency
Telegram rate limits
HTTP latency
cache hit rate
DB contention
queue depth
CPU
RAM
disk
media throughput
AI latency
```

Tune bounded concurrency, cache sizes, queue policy, batching, and cleanup only from evidence.

---

# Phase 14 — Optional Isolation

Only if workloads prove it necessary:

- dedicated heavy-worker processes;
- restricted subprocess profiles;
- containers for genuinely untrusted workloads;
- separate services for measured scaling requirements.

No fake sandbox claims.

---

# Phase 15 — Platform Maturity

Potential deliverables:

- documented plugin SDK;
- compatibility/version policy;
- safe enable/disable;
- migration tooling;
- comprehensive self-test;
- benchmarks;
- disaster recovery procedures;
- feature flags;
- release checklist.

## Global Definition of Done

Astra is platform-mature when:

1. plugin lifecycle is observable;
2. command conflicts cannot hide;
3. long-lived tasks are supervised;
4. durable work survives restart;
5. shared HTTP/subprocess/media infrastructure is used;
6. cache is bounded and measurable;
7. persistence is migration-driven;
8. high-risk plugins have regression tests;
9. AI is provider-independent and optional;
10. diagnostics expose real health;
11. resource use is bounded;
12. secrets remain protected;
13. new features reuse infrastructure;
14. the core remains ₹0/$0.

## Execution Discipline

```text
RESEARCH
   ↓
AUDIT
   ↓
DECIDE
   ↓
DOCUMENT
   ↓
IMPLEMENT
   ↓
TEST
   ↓
MIGRATE
   ↓
VERIFY
   ↓
EXPAND
   ↓
MEASURE
```

> **Build the platform once. Make every later plugin cheaper, safer, and faster to build.**
