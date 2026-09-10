# AstraUserbot — Canonical Roadmap

**Status:** Canonical implementation roadmap  
**Version:** 1.0 — reconciled with repository audit  
**Scope:** Telegram userbot platform, plugin ecosystem, reliability, automation, media, AI, search, and operations  
**Cost target:** ₹0 / $0

> This root `ROADMAP.md` is the canonical implementation sequence. Future roadmap changes should be recorded here and, when architectural, in `DECISIONS.md`.

## 0. Non-Negotiable Rules

```text
Telethon remains Telegram transport.
Plugins remain modular.
Shared services own shared infrastructure.
Durable work is persisted.
AI is advisory.
Secrets stay out of source/logs/audits.
Resource usage is bounded.
Verification matters.
Existing behavior is preserved during migration.
Core operation remains free.
```

Do not mass-rewrite the plugin ecosystem before platform services exist.

---

# Phase 0 — Baseline & Protection ✓

**Goal:** establish a reproducible repository and protect the current system.

### Deliverables

- Git repository and GitHub remote
- baseline commit
- `.gitignore`
- `.env.example`
- secret/session protection
- dependency inventory
- plugin inventory
- source-level plugin audit
- architecture documentation

### Exit criteria

- clean baseline;
- runtime secrets excluded;
- current behavior understood;
- confirmed high-risk defects recorded.

---

# Phase 1 — Plugin & Command Foundation

**Goal:** make plugin startup and command registration truthful, deterministic, and diagnosable.

## 1.1 Plugin lifecycle

Implement:

```text
DISCOVERED
LOADED
RUNNING
FAILED_IMPORT
FAILED_SETUP
DISABLED
UNLOADED
```

Add plugin metadata, dependency handling, ownership, and startup reporting.

## 1.2 Command router

Implement:

- canonical command names;
- aliases;
- duplicate detection;
- plugin ownership;
- permission metadata;
- descriptions;
- execution timing;
- correlation IDs;
- safe error boundaries.

### Immediate defect

Resolve duplicate `.block` / `.unblock` registration between ACL and PM guard.

## 1.3 Safe errors

Users receive concise error IDs. Detailed traceback stays in redacted logs.

## 1.4 Task supervision

Introduce a TaskSupervisor for long-lived process tasks and retain TaskGroup for structured short-lived concurrency.

### Phase 1 exit gate

- duplicate commands cannot silently coexist;
- plugin failures are visible;
- startup health is truthful;
- background tasks are owned and cancellable;
- command errors do not leak internals.

---

# Phase 2 — Shared Runtime Services

**Goal:** remove duplicated infrastructure hidden inside plugins.

## 2.1 Application Context

Create a shared context/service registry exposing stable interfaces.

## 2.2 SubprocessService

Centralize:

- argv execution;
- timeout;
- cancellation;
- output caps;
- exit classification;
- working directory;
- safe logging.

## 2.3 HTTP Service

Centralize:

- aiohttp session;
- connection pooling;
- timeouts;
- per-host limits;
- response-size limits;
- safe retries;
- Retry-After;
- cache hooks;
- telemetry.

Migrate network/OSINT plugins gradually.

## 2.4 Telegram facade

Provide common send/edit/delete/entity/media helpers while preserving raw Telethon access.

## 2.5 Filesystem/temp service

Provide canonical path validation, per-job temporary workspaces, cleanup, and file limits.

### Phase 2 exit gate

- shared HTTP service works;
- subprocess policy is centralized;
- temporary workspaces are reliable;
- Telegram common helpers are reusable;
- no broad plugin rewrite required.

---

# Phase 3 — Cache Foundation

**Goal:** build reusable cache infrastructure before deeper plugin migration.

## L1 Memory

- TTL;
- LRU;
- bounded entries/memory;
- namespaces;
- versioned keys;
- hit/miss metrics.

## L2 SQLite

- persistent metadata/API cache;
- TTL;
- namespace;
- source;
- content type;
- ETag/Last-Modified where useful.

## L3 Filesystem

- media;
- thumbnails;
- generated artifacts;
- large responses.

## Required behavior

- stampede protection;
- invalidation;
- size limits;
- retention;
- safe serialization.

### Phase 3 exit gate

A plugin can use one standard cache API instead of inventing a new cache implementation.

---

# Phase 4 — Storage & Persistence Foundation

**Goal:** establish durable shared SQLite infrastructure.

### Work

- migration framework;
- shared platform database;
- repositories;
- job/event tables;
- cache tables;
- audit tables;
- plugin metadata;
- integrity checks;
- retention policies;
- backup/restore of Lab state.

Existing plugin databases remain until their consumers are migrated and tested.

---

# Phase 5 — Durable Job Engine

**Goal:** make restart-sensitive automation durable.

### Core states

```text
QUEUED
RUNNING
PAUSED
VERIFYING
COMPLETED
FAILED
CANCELLED
```

### Required capabilities

- durable creation;
- worker leases;
- retry classification;
- exponential backoff + jitter;
- idempotency hooks;
- cancellation;
- startup recovery;
- parent/child jobs;
- progress/checkpoints;
- verification state;
- audit events.

### Initial job types

```text
REMINDER
SCHEDULED_MESSAGE
HTTP_TASK
MEDIA_PROCESS
DOWNLOAD
UPLOAD
INDEX
BACKUP
MAINTENANCE
AI_TASK
PLUGIN_TASK
```

### Phase 5 exit gate

Process restart, network interruption, worker failure, cancellation, and retry cannot silently erase or falsely complete durable work.

---

# Phase 6 — Fix Existing High-Risk Plugins

**Goal:** repair confirmed defects before feature expansion.

## Priority fixes

1. `.block`/`.unblock` command collision.
2. Missing advertised admin commands (`demote`, `slow`).
3. Replace base64 vault with a proper SecretStore.
4. Serialize and control `system/eval.py` global stdout manipulation.
5. Remove silent persistence failure in account archiver.
6. Add retention to archive/logger/message caches.
7. Refresh PMGuard contact state rather than caching forever.
8. Add AFK per-user cooldown/rate limiting.
9. Fix media output selection and cleanup.
10. Put rclone/aria2/media execution through SubprocessService.

### Exit gate

All P0 defects have regression tests.

---

# Phase 7 — Media Platform

**Goal:** consolidate media functionality.

### MediaService

- unique job workspaces;
- download;
- MIME detection;
- FFmpeg;
- conversion;
- audio extraction;
- speech/transcription hooks;
- thumbnails;
- output validation;
- cleanup;
- cancellation.

Migrate:

- `media/ffmpeg.py`;
- `advanced/mediaflow.py`;
- `media_ops/video.py`;
- `media_ops/speech.py`;
- `media_ops/stream.py`.

No plugin should select job output by scanning a shared directory for the newest file.

---

# Phase 8 — AI Gateway

**Goal:** remove provider lock-in and make AI optional.

### Gateway

```text
AI Gateway
 ├── Ollama
 ├── llama.cpp where useful
 ├── Groq adapter
 └── other zero-cost adapters as available
```

### Capabilities

- chat;
- summarization;
- extraction;
- classification;
- transcription integration;
- embeddings later;
- caching;
- fallback policy.

### Rules

- no provider-specific business logic in plugins;
- model IDs are configuration;
- AI unavailable must not break the bot;
- secrets are excluded from prompts;
- AI cannot bypass permissions.

---

# Phase 9 — Plugin Migration Program

**Goal:** migrate the existing ecosystem to shared infrastructure in batches.

### Batch A — security/admin

ACL, PMGuard, logger, archiver, vault, eval, admin.

### Batch B — network

DNS, IP info, headers, speedtest, and related HTTP consumers.

### Batch C — media

FFmpeg, mediaflow, stream, video, speech, aria2, rclone.

### Batch D — system/automation

AFK, autopost, sysinfo, maintenance, testall.

### Batch E — AI/advanced

Groq client, ask, summarize, transcription, advanced workflows.

Each migration must:

1. preserve existing behavior;
2. add regression tests;
3. use shared service;
4. remove duplicate infrastructure;
5. update documentation;
6. verify startup/command health.

---

# Phase 10 — Search & Knowledge

**Goal:** make the growing plugin/runtime state searchable.

### Levels

```text
1. plugin/command metadata
2. notes and structured data
3. message cache
4. SQLite FTS5
5. OCR/transcripts
6. semantic retrieval later
```

Search state is derived and rebuildable.

---

# Phase 11 — Observability & Diagnostics

**Goal:** make the bot able to explain its own operational state.

Initial commands:

```text
!health
!plugins
!tasks
!jobs
!cache
!stats
!diagnostics
```

Future:

```text
!db
!http
!media
!ai
```

Diagnostics should show:

- loaded/failed plugins;
- command conflicts;
- task status;
- job backlog;
- cache hit/miss;
- DB health;
- HTTP health;
- resource pressure;
- recent errors.

No secrets.

---

# Phase 12 — Automation Expansion

**Goal:** add a large feature surface on proven primitives.

Candidate families:

- advanced Telegram utilities;
- reminders;
- scheduled messages;
- notes/bookmarks;
- message tools;
- bulk operations;
- media tools;
- download/upload workflows;
- RSS/feed automation;
- web utilities;
- developer tools;
- Linux/system utilities;
- knowledge/search;
- backup/export;
- AI-assisted utilities;
- fun/social modules.

Every feature plugs into shared services rather than implementing its own infrastructure.

---

# Phase 13 — Performance & Resource Optimization

**Goal:** optimize from measurements rather than guesses.

Measure:

- event latency;
- command latency;
- HTTP latency;
- cache hit rate;
- DB contention;
- queue depth;
- memory;
- CPU;
- media throughput;
- Telegram rate-limit frequency.

Then tune bounded concurrency, cache sizes, batch sizes, and scheduling.

---

# Phase 14 — Optional Advanced Isolation

**Goal:** introduce stronger isolation only if evidence demands it.

Possible future mechanisms:

- dedicated worker processes for heavy media/AI;
- restricted subprocess profiles;
- containers for genuinely untrusted workloads;
- separate service processes for proven scaling needs.

This phase is intentionally deferred. Python plugin isolation is not claimed merely because modules are separate.

---

# Phase 15 — Platform Maturity

**Goal:** make AstraUserbot a stable extensible platform.

Potential deliverables:

- documented plugin SDK;
- compatibility/version policy;
- plugin health dashboard;
- migration tooling;
- self-test suite;
- performance benchmarks;
- disaster/recovery procedures;
- feature flags;
- safe plugin disable/enable;
- release checklist.

---

# Global Exit Criteria

AstraUserbot is considered architecturally mature when:

1. all plugins load through an observable lifecycle;
2. command collisions are impossible to ignore;
3. long-lived work has explicit supervision or durability;
4. shared HTTP/subprocess/media infrastructure is centralized;
5. cache behavior is bounded and measurable;
6. SQLite persistence is migrated through tested schemas;
7. durable jobs survive restart;
8. high-risk plugins have regression coverage;
9. AI is provider-independent and optional;
10. diagnostics expose real platform health;
11. resources remain bounded;
12. secrets remain protected;
13. the feature surface can grow without duplicating infrastructure;
14. core operation remains ₹0 / $0.

## Implementation Philosophy

```text
RESEARCH
   ↓
AUDIT
   ↓
ARCHITECTURE
   ↓
PLATFORM SERVICES
   ↓
FIX
   ↓
MIGRATE
   ↓
TEST
   ↓
EXPAND FEATURES
   ↓
MEASURE
   ↓
OPTIMIZE
```

> **Build the platform once, then let the plugins become thin capability modules.**
