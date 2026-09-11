# AstraUserbot — Detailed Canonical Roadmap

**Status:** Canonical implementation sequence  
**Version:** 2.4  
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

# Phase 2 — Shared Runtime Services — COMPLETE

**Goal:** extract duplicated infrastructure into explicit, reusable process-wide services.

## 2.1 Application Context — COMPLETE

Implemented `ApplicationContext` with explicit service ownership, deterministic startup/shutdown, service lookup, runtime snapshot and startup failure cleanup.

Current core services include:

```text
HttpService
SubprocessService
TelegramFacade
WorkspaceService
MediaService
AIService
```

## 2.2 SubprocessService — COMPLETE

Implemented bounded argv execution, timeout/cancellation handling, output caps, cwd policy, explicit environment passing and controlled error classification.

## 2.3 HttpService — COMPLETE

Implemented one shared aiohttp session, pooling, per-host limits, request timeouts, response-size limits, bounded transient retries, redirect policy and cancellation propagation.

## 2.4 TelegramFacade — COMPLETE

Implemented common Telegram operations with bounded FloodWait handling while preserving raw Telethon access through the client.

## 2.5 Filesystem/WorkspaceService — COMPLETE

Implemented canonical workspace root, unique operation workspaces, traversal-safe paths, managed-file size validation, deterministic cleanup and orphan cleanup.

### Gate 2

**PASS — Phase 2 service regression suite passed.**

---

# Phase 3 — Cache Foundation — COMPLETE

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

**PASS — 49/49 full regression tests passed.**

---

# Phase 4 — Storage & Migration Foundation — COMPLETE

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

**PASS — deterministic platform storage/migration validation is complete.**

---

# Phase 5 — Durable Job Engine — COMPLETE

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

### Gate 5

**PASS — uncertain external outcomes require explicit reconciliation before replay.**

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

### Gate 6

**PASS — 73 tests passed and compile validation passed.**

---

# Phase 7 — Media Platform — COMPLETE

**Goal:** make media a reusable, bounded, isolated service.

## 7.1 MediaService — COMPLETE

`core/services/media.py` is the authoritative media boundary. It provides:

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

## 7.2 Consumer migration — COMPLETE

All Phase 7 media consumers use `MediaService`:

```text
media/ffmpeg.py
advanced/mediaflow.py
media_ops/video.py
media_ops/speech.py
media_ops/stream.py
media/aria2.py
media/rclone.py
```

## 7.3 Concurrency and verification — COMPLETE

Media execution is bounded by a service-level semaphore. Artifact validation enforces non-empty regular-file outputs and size limits. FFmpeg output verification, deterministic download manifests, TTS verification, workspace cleanup and rclone operation policy are covered by regression tests.

### Gate 7 — PASS

**81/81 tests passed, 0 failures, 0 errors, and compile validation passed.**

---

# Phase 8 — AI Gateway — COMPLETE

**Goal:** remove provider lock-in while preserving existing AI command behavior.

## 8.1 Provider-independent service — COMPLETE

Created `core/services/ai.py` and registered it in `ApplicationContext`.

The gateway owns:

```text
chat
summarize
extract
classify
transcribe
provider selection
model configuration
input/output bounds
audio size bounds
bounded concurrency
cancellation
provider capability checks
safe error translation
```

## 8.2 Adapters — COMPLETE

Implemented adapters for:

```text
Groq
Google Gemini Developer API
Ollama / OpenAI-compatible local endpoint
llama.cpp / OpenAI-compatible local endpoint
```

Local adapters are optional. No local model is required for startup or runtime architecture.

## 8.3 Existing command migration — COMPLETE

The user-facing commands remain:

```text
.ask
.summarize
.transcribe
```

New adapters live under `plugins/ai_gateway/` and resolve `AIService` from `ApplicationContext`. The previous Groq-specific command modules are quarantined from runtime discovery so duplicate command ownership cannot occur.

## 8.4 Reliability/security contract — COMPLETE

- provider secrets remain environment configuration;
- provider response bodies are not exposed through user-facing errors;
- request and output sizes are bounded;
- audio uploads are bounded;
- HTTP retries remain bounded and centralized;
- cancellation propagates through the gateway;
- AI concurrency is bounded;
- unsupported capabilities fail explicitly;
- AI output remains untrusted data and cannot authorize privileged actions;
- no paid AI SDK or mandatory paid service was introduced.

### Gate 8 — PASS

**Phase 8 implementation and contract tests are complete.** The gateway is provider-independent, plugin-level Groq API knowledge is removed from the active command path, and the local provider adapters remain optional.

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

### Migration note

The Phase 8 AI command migration is already complete and therefore is excluded from future Batch E work except for removal of the quarantined compatibility artifacts when the compatibility exit criteria are satisfied.

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
