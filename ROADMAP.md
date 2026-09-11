# AstraUserbot — Detailed Canonical Roadmap

**Status:** Canonical implementation sequence  
**Version:** 2.3  
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

### Phase 1 tests

- duplicate command;
- duplicate alias;
- plugin import failure;
- plugin setup failure;
- dependency cycle;
- registration cleanup;
- task crash visibility;
- shutdown cancellation;
- safe error output;
- real plugin-tree integration.

### Gate 1 — PASS

**28/28 tests passed and compile validation passed.**

---

# Phase 2 — Shared Runtime Services — IMPLEMENTED

**Goal:** extract duplicated infrastructure into explicit, reusable process-wide services.

## 2.1 Application Context — COMPLETE

Implemented `ApplicationContext` with:

- explicit service ownership;
- deterministic startup order;
- reverse shutdown order;
- service lookup/typing helpers;
- runtime snapshot;
- process-level compatibility accessor;
- failure cleanup during startup.

Current core services:

```text
HttpService
SubprocessService
TelegramFacade
WorkspaceService
MediaService
```

## 2.2 SubprocessService — COMPLETE

Implemented:

- argv execution without shell interpretation;
- timeout and cancellation handling;
- bounded stdout/stderr;
- output-limit termination;
- cwd policy;
- explicit environment passing;
- controlled error classification;
- safe program-level logging.

`helpers/shell.py` now routes through this service.

## 2.3 HttpService — COMPLETE

Implemented:

- one shared `aiohttp.ClientSession`;
- connection pooling;
- per-host concurrency limits;
- request timeouts;
- response-size limits;
- bounded transient retries;
- redirect policy;
- cancellation propagation;
- safe external-service errors;
- restartable service lifecycle.

`helpers/net.py` now resolves the runtime HTTP session from the ApplicationContext.

## 2.4 TelegramFacade — COMPLETE

Implemented common operations for:

```text
send_message
send_file
edit_message
delete_messages
get_entity
```

Also provides bounded FloodWait handling while preserving raw Telethon access through the client.

## 2.5 Filesystem/WorkspaceService — COMPLETE

Implemented:

- canonical workspace root;
- unique per-operation workspaces;
- traversal-safe path resolution;
- managed-file size validation;
- deterministic cleanup;
- orphan cleanup;
- workspace isolation.

### Gate 2

Phase 2 service regression coverage includes:

- ApplicationContext startup/shutdown;
- duplicate service protection;
- subprocess argv execution;
- subprocess output bounds;
- subprocess timeout;
- workspace isolation and traversal protection;
- workspace file-size limits;
- Telegram facade delegation;
- HTTP response limits;
- HTTP cancellation;
- HTTP service restartability.

**Implementation gate is complete; run the local suite below before treating the working checkout as verified.**

---

# Phase 3 — Cache Foundation

**Goal:** establish the reusable cache before broad plugin migration.

## L1

TTL/LRU, bounded entries/bytes, namespaces, versioned keys, hit/miss metrics, stampede locks.

## L2

SQLite cache metadata/value storage with TTL, source, content type, validators, size and access metadata.

## L3

Filesystem artifacts for large media/binary data with SQLite metadata references.

## Cache policies

- explicit expiry/invalidation;
- namespace isolation;
- safe serialization;
- byte/count limits;
- negative caching only when useful;
- orphan cleanup;
- diagnostics.

### Gate 3

A plugin can use one cache API for memory, persistent metadata, and large artifacts without inventing its own cache.

---

# Phase 4 — Storage & Migration Foundation

**Goal:** create durable shared platform persistence.

### Deliverables

- migration runner;
- schema version table;
- platform SQLite DB;
- repositories;
- foreign keys;
- WAL configuration;
- busy timeout;
- integrity checks;
- retention service;
- backup/restore tests.

### Migration rule

Existing plugin DBs stay intact until each migration is backed up, tested, verified, and reversible.

### Gate 4

A clean install and an existing install both reach the same expected platform schema through deterministic migrations.

---

# Phase 5 — Durable Job Engine

**Goal:** make restart-sensitive work durable.

## Required

- persistent job creation;
- state machine;
- worker leases;
- heartbeats;
- bounded retry/backoff;
- failure classes;
- idempotency hooks;
- cancellation;
- parent/child jobs;
- progress;
- startup recovery;
- verification state;
- audit events;
- resource classes;
- explicit `UNCERTAIN` state for unknown execution outcomes.

## Initial job types

```text
REMINDER
SCHEDULED_MESSAGE
HTTP_TASK
DOWNLOAD
UPLOAD
MEDIA_PROCESS
INDEX
BACKUP
MAINTENANCE
SYNC
AI_TASK
PLUGIN_TASK
```

### Crash scenarios to test

```text
crash before execution
crash during execution
crash after external side effect
crash during verification
lease expiry
network outage
DB restart
cancellation
```

### Gate 5

The system never silently loses accepted durable work and never blindly replays an uncertain external mutation. Expired leases and interrupted active work enter `UNCERTAIN` and require explicit reconciliation before replay.

---

# Phase 6 — Confirmed P0 Reliability Fixes — COMPLETE

**Goal:** repair high-risk existing features before expansion.

1. ACL/PMGuard duplicate commands.
2. Implement/fix advertised admin `demote` and `slow` semantics.
3. Consolidate vaults into SecretStore; remove base64-as-encryption semantics.
4. Serialize eval output capture and impose practical limits.
5. Surface account-archiver persistence errors.
6. Add archive/message/logger retention.
7. Refresh PMGuard contacts through cache/invalidation.
8. Add AFK sender cooldown.
9. Fix stream output identity and per-job workspace.
10. Normalize media cleanup on all paths.
11. Route rclone/aria2 through SubprocessService.
12. Remove provider/network duplication as migrations permit.

### Gate 6

**PASS — 73 tests passed and compile validation passed at the Phase 6 baseline.** The final pre-Phase-7 hardening also adds regression coverage for uncertain durable-job recovery; the complete pre-Phase-7 suite passed before media implementation.

---

# Phase 7 — Media Platform — COMPLETE

**Goal:** make media a reusable, bounded, isolated service.

## 7.1 MediaService — COMPLETE

`core/services/media.py` is now the authoritative media boundary. It provides:

```text
unique workspace allocation
input validation
output verification
explicit artifact manifests
deterministic external execution
FFmpeg / FFprobe helpers
TTS helper
download helper
rclone policy boundary
workspace size limits
input/output size limits
bounded media concurrency
cleanup
```

The service uses `WorkspaceService` and `SubprocessService`; media plugins no longer create shared `data/cache` workspaces or invoke the legacy shell helper directly.

## 7.2 Consumer migration — COMPLETE

All Phase 7 media consumers now use `MediaService`:

```text
media/ffmpeg.py
advanced/mediaflow.py
media_ops/video.py
media_ops/speech.py
media_ops/stream.py
media/aria2.py
media/rclone.py
```

Key migration properties:

- every operation receives a unique workspace;
- FFmpeg commands are explicit argv arrays;
- download outputs are returned as verified artifact manifests rather than selected by filesystem mtime;
- media input/output/workspace bounds are enforced;
- FFprobe verification is performed when available for FFmpeg-produced artifacts;
- TTS output is verified before upload;
- rclone operations are limited to the explicit media policy allowlist;
- every consumer cleans its workspace in `finally` paths.

## 7.3 Concurrency and verification — COMPLETE

Media execution is bounded by a service-level semaphore, while artifact validation enforces non-empty, regular-file, size-limited outputs. The media gate includes regression coverage for isolation, size limits, deterministic FFmpeg argv, verification, concurrency, and rclone policy.

### Gate 7 — PASS PENDING LOCAL REGRESSION

Implementation is complete. The working checkout must pass the complete local suite and compile validation before this gate is marked verified in the release state.

---

# Phase 8 — AI Gateway

**Goal:** remove provider lock-in.

### Interface

```text
chat
summarize
extract
classify
transcribe
embed (future)
```

### Adapters

```text
Ollama/local
llama.cpp/local where useful
Groq
other genuinely free adapters
```

### Rules

- provider details stay in adapters;
- models are configuration;
- requests have bounded input/output;
- cache where useful;
- cancellation works;
- secrets are excluded;
- AI failure degrades gracefully;
- AI cannot bypass authorization.

### Gate 8

`ask`, `summarize`, and transcription-related workflows no longer require plugin-level knowledge of the Groq API.

---

# Phase 9 — Plugin Migration Program

**Goal:** move the existing ecosystem onto platform services.

## Batch A — Security/Admin

ACL, PMGuard, logger, account archiver, vault, eval, admin.

## Batch B — Network/OSINT

DNS, IP info, headers, speedtest and other HTTP consumers.

## Batch C — Media

FFmpeg, mediaflow, stream, video, speech, aria2, rclone.

## Batch D — System/Automation

AFK, autopost, sysinfo, maintenance, testall.

## Batch E — AI/Advanced

Groq client, ask, summarize, transcription and advanced workflows.

### Every migration must

1. preserve intended behavior;
2. add regression coverage;
3. use shared service contracts;
4. remove duplicate infrastructure;
5. verify cleanup/failure behavior;
6. update documentation;
7. run startup/command smoke tests.

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
