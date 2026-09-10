# AstraUserbot — Detailed Architecture Specification

**Status:** Canonical architectural contract  
**Version:** 2.0  
**Scope:** Core runtime, plugin platform, Telegram, persistence, jobs, cache, media, AI, search, observability, security, testing, and migration  
**Cost target:** ₹0 / $0

## 1. Purpose

AstraUserbot is a long-lived Telegram userbot platform built with Python, Telethon, and asyncio. The repository already contains a broad plugin ecosystem plus SQLite state, HTTP clients, subprocess/media workflows, AI integrations, account/security automation, and scheduled work.

The goal is **not** to replace that ecosystem with a framework. The goal is to extract the infrastructure already duplicated inside it and establish deterministic contracts around lifecycle, authorization, persistence, execution, verification, and recovery.

The target architecture is a **single-process service-oriented modular monolith**.

## 2. Architectural Invariants

These rules outrank convenience:

1. Telethon remains the Telegram transport.
2. Plugins remain independently organized capabilities.
3. Shared infrastructure has one authoritative implementation.
4. Durable work is persisted before being called durable.
5. Execution success and verification success are distinct.
6. AI is untrusted/advisory and cannot grant authority.
7. Cache and indexes are derived state.
8. Secrets never enter source control, normal logs, audits, or prompts unnecessarily.
9. Long-lived ephemeral tasks are supervised.
10. High-impact actions require explicit authorization and bounded scope.
11. Resource consumption is bounded.
12. Existing behavior is preserved during migration unless a defect is intentionally fixed.
13. The platform remains usable at ₹0/$0.
14. Uncertainty causes reconciliation or refusal, not increasingly broad automation.

## 3. System Topology

```text
Telegram / local trigger / scheduler
                │
                ▼
        Event + Command Router
                │
        validate / correlate
                │
                ▼
        Authorization / Policy
                │
                ▼
          Application Context
       ┌────────┼──────────────┐
       ▼        ▼              ▼
    Plugins   Job Engine   Service Registry
       │        │              │
       └────────┼──────────────┘
                │
   ┌────────────┼─────────────────────────┐
   ▼            ▼            ▼            ▼
 Telegram     HTTP       Subprocess     Cache
   │            │            │            │
   └────────────┼────────────┼────────────┘
                ▼
       Storage / Media / AI
                │
                ▼
        Verify + Audit + Report
```

## 4. Runtime Layers

### Layer 0 — Transport

Telethon client/session/event delivery. This layer knows Telegram mechanics, not plugin business rules.

### Layer 1 — Core runtime

Bootstrap, configuration, lifecycle, correlation IDs, error boundaries, task supervision, service ownership.

### Layer 2 — Platform services

Router, authorization, storage, cache, HTTP, subprocess, Telegram facade, media, AI, jobs, audit, search, diagnostics.

### Layer 3 — Plugins

Feature modules. Plugins consume services; they should not recreate them.

### Layer 4 — External systems

Telegram, web APIs, local programs, filesystem, model runtimes, configured storage targets.

## 5. Application Context

`ApplicationContext` is the runtime dependency boundary. Conceptually:

```python
ctx.telegram
ctx.router
ctx.plugins
ctx.tasks
ctx.jobs
ctx.http
ctx.cache
ctx.storage
ctx.media
ctx.ai
ctx.audit
ctx.config
ctx.metrics
```

The context is created once during bootstrap, passed explicitly where practical, and closed in reverse dependency order. It must not become an uncontrolled mutable global registry.

### Context lifecycle

```text
CREATE
  ↓
CONFIGURE
  ↓
OPEN DEPENDENCIES
  ↓
LOAD PLUGINS
  ↓
START RUNTIME
  ↓
RUN
  ↓
QUIESCE
  ↓
STOP JOB WORKERS/TASKS
  ↓
UNLOAD PLUGINS
  ↓
CLOSE SERVICES
  ↓
DISCONNECT TELEGRAM
```

## 6. Plugin Contract

Every plugin eventually exposes metadata:

```text
name
version
api_version
dependencies
optional_dependencies
permissions/capabilities
description
```

Lifecycle:

```text
DISCOVERED → LOADED → RUNNING
                 ├→ FAILED_SETUP
                 └→ DISABLED
RUNNING → UNLOADED
DISCOVERED → FAILED_IMPORT
```

The Plugin Manager owns:

- deterministic discovery;
- import isolation;
- metadata validation;
- dependency ordering;
- cycle detection;
- command/event ownership;
- task ownership;
- setup/shutdown;
- health state;
- compatibility adapters.

A failed plugin must be visible in startup diagnostics. Startup must not report fully healthy when required plugins failed.

### Legacy compatibility

Existing `setup()` plugins continue to work through an adapter while the new contract is introduced. Compatibility code is removed only after migration and regression tests.

## 7. Command Router

The router is the single registration authority.

Each command record contains:

```text
canonical name
aliases
plugin owner
handler
permission/capability
side-effect class
description
registration source
state
```

Registration algorithm:

1. normalize command and aliases;
2. validate syntax;
3. check existing ownership;
4. reject duplicate active names/aliases;
5. register handler;
6. persist/record metadata;
7. expose diagnostics.

Aliases map to the same command definition. A plugin cannot silently overwrite another plugin.

### Current known collision

`.block` and `.unblock` exist in both ACL and PMGuard. Phase 1 must make this impossible to register silently, then establish the intended single owner.

## 8. Request Execution Contract

Side-effecting requests use:

```text
REQUEST
  ↓
VALIDATE
  ↓
AUTHORIZE
  ↓
PLAN
  ↓
EXECUTE
  ↓
VERIFY
  ↓
AUDIT
  ↓
REPORT
```

Read-only commands may collapse stages, but they still validate input and report failures safely.

The router owns correlation/error IDs. Plugins return typed results/errors where practical rather than sending arbitrary exceptions directly to Telegram.

## 9. Authorization and Capabilities

Initial policy levels:

```text
OWNER
ADMIN
TRUSTED
PUBLIC
```

Capabilities are finer-grained:

```text
telegram.read
telegram.write
telegram.moderate
filesystem.read
filesystem.write
subprocess.execute
network.request
media.process
ai.inference
account.control
security.manage
```

Authorization is evaluated before execution. A capability declaration alone is not authorization; the policy layer must enforce it.

## 10. Task Supervision

### Structured concurrency

Use `asyncio.TaskGroup` for bounded groups where sibling failure should be coordinated.

### TaskSupervisor

Long-lived process tasks are registered with:

```text
name
owner
created_at
task
restart policy
shutdown behavior
last error
```

Examples: Telegram watchers, cleanup loops, cache maintenance, job polling.

### Durable jobs

If work must survive restart, it is a Job Engine concern. Never advertise an in-memory task as durable.

## 11. Shared HTTP Service

One shared `aiohttp.ClientSession` is created by the runtime.

Responsibilities:

- connection pooling;
- total/connect/read timeouts;
- per-host concurrency;
- response-size caps;
- redirect policy;
- retry classification;
- `Retry-After` handling;
- cancellation;
- request timing;
- cache hooks;
- safe logging.

Retries are limited to safe transient situations. Non-idempotent mutations are not blindly replayed.

HTTP features accepting arbitrary URLs require explicit URL/scheme/redirect policy and must not accidentally become unlimited downloaders.

## 12. Subprocess Service

All external commands eventually pass through a shared service.

Contract:

```text
argv
cwd
environment policy
timeout
output limits
cancellation
resource policy
result classification
```

Execution uses `create_subprocess_exec`/argv semantics, not shell interpolation. The service records timing and exit class without dumping arbitrary output into logs.

Existing consumers include FFmpeg, rclone, aria2c, speech tools, OCR, and system utilities.

## 13. Filesystem and Workspace Service

Canonical roots:

```text
SOURCE_ROOT
DATA_ROOT
CACHE_ROOT
TEMP_ROOT
USER_EXPORT_ROOT
PROTECTED_ROOTS
```

Path handling must canonicalize and enforce roots. Each media/download job receives a unique workspace:

```text
cache/jobs/<job-id>/
  input/
  output/
  metadata.json
```

Cleanup runs on success, failure, and cancellation. Orphan cleanup is part of startup maintenance.

## 14. Cache Architecture

### L1 — Memory

Bounded TTL/LRU entries with namespace and version. Suitable for hot entity/config/message state.

### L2 — SQLite

Persistent API/metadata cache with:

```text
namespace
key
version
created_at
expires_at
last_accessed_at
source
content_type
etag
last_modified
payload/reference
size
```

### L3 — Filesystem

Large binaries/media/thumbnails/generated artifacts. SQLite stores metadata and references.

### Cache rules

- explicit TTL or invalidation;
- bounded capacity;
- namespace isolation;
- safe serialization;
- stampede locks for expensive refreshes;
- negative caching only where useful;
- versioned keys when schemas change;
- cache loss must never imply data loss.

## 15. Storage Architecture

SQLite remains the default persistence system.

Required baseline:

- WAL where appropriate;
- foreign keys;
- busy timeout;
- numbered migrations;
- short transactions;
- repository/data-access boundaries;
- integrity checks;
- retention policies;
- backup/restore tooling.

Long-term shared infrastructure tables include plugins, commands, jobs, job events, cache, audit, health, settings, and media metadata. Existing plugin databases remain until migration is proven safe.

No network call is held open inside a database transaction.

## 16. Durable Job Engine

Durable work uses SQLite persistence and explicit state transitions:

```text
QUEUED → RUNNING → VERIFYING → COMPLETED
             │          │
             ├→ QUEUED  ├→ QUEUED
             ├→ PAUSED  └→ FAILED
             ├→ FAILED
             └→ CANCELLED
```

Jobs support leases, retries, idempotency, progress, parent/child workflows, cancellation, recovery, verification, and audit.

A lease expiry means **uncertain execution**, never success.

## 17. Media Architecture

`MediaService` becomes the common boundary for:

- download;
- MIME detection;
- FFmpeg;
- conversion;
- extraction;
- speech/transcription;
- thumbnails;
- upload preparation;
- cleanup.

Plugins become request/response wrappers.

A job must never discover its result by scanning a shared directory for the newest file. Output paths are deterministic and job-owned.

## 18. Telegram Facade

`ctx.telegram` provides common operations:

- send/edit/delete;
- download/upload;
- entity lookup;
- common retry/flood handling;
- formatting helpers;
- bounded media operations.

Raw Telethon remains available for advanced plugins. The facade centralizes policy, not every Telethon feature.

## 19. AI Gateway

The AI layer exposes provider-independent operations:

```text
chat
summarize
extract
classify
transcribe
embed (future)
```

Adapters can include:

```text
Ollama/local
llama.cpp/local
Groq
other genuinely free providers when configured
```

Plugins never depend directly on provider URLs/model constants. AI failure degrades the feature rather than the entire bot.

AI output is data. It cannot execute, authorize, broaden scope, reveal secrets, or bypass deterministic policy.

## 20. Search

Initial search uses SQLite indexes and FTS5 where justified.

Potential sources:

```text
plugin metadata
command metadata
notes
messages
OCR
transcripts
structured plugin records
```

Indexes are rebuildable derived state. Vector/semantic retrieval is optional future infrastructure, not a prerequisite.

## 21. Observability

Minimum operational views:

```text
!health
!plugins
!tasks
!jobs
!cache
!stats
!diagnostics
```

Diagnostics should expose:

- plugin load/failure state;
- command conflicts;
- task crashes;
- job backlog/leases;
- cache hit/miss;
- DB integrity/latency;
- HTTP state;
- media workspaces;
- resource pressure;
- recent classified errors.

Diagnostics never expose session strings, API keys, cookies, passwords, or raw secret-bearing responses.

## 22. Error Model

Errors have stable classes/codes:

```text
AUTH_DENIED
INVALID_INPUT
NOT_FOUND
CONFLICT
RATE_LIMITED
TIMEOUT
NETWORK_ERROR
RESOURCE_LIMIT
INTEGRITY_FAILED
CANCELLED
UNSUPPORTED
INTERNAL_ERROR
```

User-facing output is concise:

```text
Operation failed [E-7F31]
```

Detailed tracebacks remain in structured, redacted logs.

## 23. Security Architecture

Astra is one Python process, so plugin modules are **not trust boundaries**. Capability declarations improve policy but do not create memory isolation.

Privileged features such as eval, filesystem writes, subprocess execution, account control, vault access, and bulk moderation require explicit authorization.

Base64 is never encryption. Secret storage uses reviewed authenticated encryption/key derivation.

## 24. Resource Model

The platform is designed for a constrained local machine. Every subsystem therefore has bounded resources:

```text
HTTP concurrency
Telegram concurrency
job workers
media workers
subprocess output
cache entries/bytes
download size
disk artifacts
DB transaction scope
AI context/output
```

Backpressure is preferred over unbounded queues or memory growth.

## 25. Plugin Migration Strategy

Migration is batch-based:

```text
Foundation
  ↓
Security/Admin
  ↓
Network/HTTP
  ↓
Media/Subprocess
  ↓
System/Automation
  ↓
AI/Advanced
```

Each migration preserves behavior, adds regression coverage, uses shared services, removes duplicate infrastructure, and verifies startup/command health.

## 26. Testing Architecture

Test layers:

1. pure unit tests;
2. service contract tests;
3. SQLite migration/repository tests;
4. plugin registration tests;
5. command conflict tests;
6. task/job lifecycle tests;
7. HTTP/subprocess policy tests;
8. media workspace tests;
9. plugin integration tests;
10. safe end-to-end smoke tests.

Network-dependent tests must be bounded and opt-in where required. Tests must never require paid APIs.

## 27. Explicitly Rejected as Defaults

Do not introduce Redis, Kafka, RabbitMQ, Celery, Kubernetes, microservices, Postgres, ORM-heavy persistence, LangChain/LlamaIndex core, LiteLLM as a mandatory dependency, Prometheus/Grafana/OTel as mandatory infrastructure, automatic hot reload, or a giant event bus without evidence.

The burden of proof belongs to the new infrastructure.

## 28. Definition of Architectural Completion

The architecture is considered implemented when:

- plugin lifecycle is observable;
- command conflicts are deterministic;
- shared services have stable contracts;
- durable jobs survive restart;
- cache is bounded;
- SQLite migrations are tested;
- media workspaces are isolated;
- AI is provider-independent;
- diagnostics are useful and secret-safe;
- P0 plugin defects have regression tests;
- feature development no longer duplicates core infrastructure.

> **AstraUserbot should be powerful at the plugin edge and boring at the infrastructure core: deterministic, bounded, observable, recoverable, and free to operate.**
