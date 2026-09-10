# AstraUserbot — Architecture

**Status:** Architecture Baseline  
**Version:** 1.0  
**Scope:** Long-lived Telegram userbot platform, automation runtime, plugin ecosystem, shared services, durable jobs, media, AI, search, and observability  
**Cost target:** ₹0 / $0

## 1. Purpose

AstraUserbot is a long-lived Telegram userbot platform built around Telethon. It is not merely a collection of command handlers. The existing repository already contains a substantial plugin surface, persistent SQLite state, HTTP integrations, subprocess/media workflows, AI integrations, security features, and background automation.

The architectural objective is to turn those capabilities into a reliable platform without requiring a destructive rewrite of the existing plugins.

The system must remain:

- single-process by default;
- asynchronous;
- local-first;
- resource-aware;
- restartable;
- observable;
- modular;
- compatible with existing plugins;
- independent of paid infrastructure;
- safe around credentials, Telegram state, subprocesses, external APIs, and destructive commands.

## 2. Core Principle

**The model is not the authority. A plugin is not the platform. A background task is not durable work. A successful command is not proof of a successful operation.**

The architecture separates:

- command routing from handler implementation;
- plugin lifecycle from plugin code;
- authorization from execution;
- planning from mutation;
- transient tasks from durable jobs;
- shared services from individual plugins;
- cache from authoritative state;
- execution from verification;
- provider adapters from provider-independent interfaces;
- diagnostics from secrets;
- optional AI from deterministic control paths.

The canonical controlled workflow is:

`REQUEST → VALIDATE → AUTHORIZE → PLAN → EXECUTE → VERIFY → REPORT`

Not every read-only operation requires every stage, but any operation with meaningful side effects must have an explicit control path.

## 3. System Shape

```text
                         Telegram / User
                               │
                               ▼
                    ┌──────────────────────┐
                    │     Event / Router   │
                    │ commands + events    │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │     Authorization    │
                    │ permissions / scope  │
                    └──────────┬───────────┘
                               │
              ┌────────────────▼────────────────┐
              │          Application Context    │
              │ shared services + configuration │
              └───────┬─────────┬─────────┬─────┘
                      │         │         │
          ┌───────────▼───┐ ┌──▼──────┐ ┌▼────────────┐
          │ Plugin Manager│ │ Job      │ │ Service     │
          │ lifecycle     │ │ Engine   │ │ Registry    │
          └───────────────┘ └──┬──────┘ └─────────────┘
                               │
                ┌──────────────┼─────────────────┐
                ▼              ▼                 ▼
          HTTP Service   Media/Subprocess    Cache/Storage
                │              │                 │
                └──────────────┼─────────────────┘
                               ▼
                         Verification / Audit
                               │
                               ▼
                         Telegram / Files /
                         External providers
```

## 4. Architectural Rules

### 4.1 Single process first

AstraUserbot remains one process unless a demonstrated workload requires isolation. Do not introduce microservices, Redis, Kafka, RabbitMQ, Kubernetes, or a remote orchestration layer merely because the plugin count is large.

### 4.2 Async by default

Telethon, HTTP, job execution, background tasks, and plugin event handlers use asyncio. Blocking work must be isolated through a controlled subprocess/thread/executor boundary.

### 4.3 Shared infrastructure is centralized

Plugins should not independently reinvent HTTP sessions, subprocess policy, temporary directories, media handling, cache semantics, database migrations, retry logic, or task supervision.

### 4.4 Existing plugins are migrated incrementally

The current plugin ecosystem is valuable working code. Platform services are built first, then plugins are migrated in batches. A migration must preserve behavior unless a deliberate bug fix or architectural change is recorded.

### 4.5 Compatibility matters

Legacy `setup()`-based plugins must continue to work while the new plugin contract is introduced. Compatibility is a migration layer, not the permanent architecture.

## 5. Application Context

A central application context owns shared runtime services.

Conceptually:

```text
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
ctx.config
ctx.audit
ctx.metrics
```

The context should avoid becoming a giant mutable global. Services have explicit interfaces and lifecycle ownership.

## 6. Plugin Architecture

Every plugin eventually has metadata equivalent to:

```text
name
version
api_version
dependencies
optional_dependencies
permissions
description
```

Lifecycle states:

```text
DISCOVERED
LOADED
RUNNING
FAILED_IMPORT
FAILED_SETUP
DISABLED
UNLOADED
```

The Plugin Manager must:

- discover plugins deterministically;
- import them safely;
- validate metadata;
- resolve dependencies;
- detect cycles;
- register commands/events;
- isolate setup failures;
- expose health information;
- track ownership of registrations;
- support clean shutdown;
- preserve legacy plugins through compatibility adapters.

A plugin that fails must not make startup appear completely healthy.

## 7. Command Router

Commands are registered centrally by command name and aliases.

The router owns:

- command name/alias mapping;
- duplicate detection;
- plugin ownership;
- descriptions;
- permission requirements;
- execution timing;
- error IDs;
- diagnostics.

Aliases point to the same handler rather than becoming independent duplicated registrations.

A duplicate command or alias is a startup/configuration error unless an explicit override policy exists.

Command failures expose a safe user-facing message and a correlation/error ID. Tracebacks, internal paths, provider responses, and sensitive arguments remain in protected logs only.

## 8. Authorization

Authorization is centralized rather than inferred separately by every plugin.

Initial conceptual levels:

```text
OWNER
ADMIN
TRUSTED
PUBLIC
```

Plugins additionally declare capabilities such as:

```text
telegram.read
telegram.write
filesystem.read
filesystem.write
subprocess.execute
network.request
external_api
ai.inference
media.process
account.control
```

Authorization determines whether a caller may invoke an operation. It is not a sandbox for the Python process itself.

## 9. Task Supervision

There are three classes of asynchronous work.

### Short bounded work

Use `asyncio.TaskGroup` for related work that should share failure/cancellation semantics.

### Long-lived runtime tasks

Use a central `TaskSupervisor`/`ctx.spawn()` registry for watchers, pollers, cleanup loops, and other process-lifetime tasks. Every task has ownership, name, cancellation, exception reporting, and shutdown behavior.

### Durable work

Use the Job Engine for work that must survive process restart, sleep, disconnect, or worker failure.

Never pretend an in-memory asyncio task is durable.

## 10. Durable Job Engine

The Job Engine persists accepted work in SQLite.

Canonical states:

```text
QUEUED
RUNNING
PAUSED
VERIFYING
COMPLETED
FAILED
CANCELLED
```

Canonical successful flow:

`QUEUED → RUNNING → VERIFYING → COMPLETED`

The engine supports leases, bounded retries, failure classification, idempotency/reconciliation hooks, cancellation, parent/child jobs, startup recovery, and audit events.

Reminders, scheduled messages, retryable automation, long media jobs, backups, indexing, and other restart-sensitive work belong here.

## 11. Cache Architecture

AstraUserbot uses a tiered cache where justified.

### L1 — Memory

TTL/LRU cache with bounded entries/memory, namespaces, versioned keys, and hit/miss statistics.

### L2 — SQLite

Persistent cache for metadata/API responses that are useful across restarts. Records include namespace, key, value, creation time, expiry, source, content type, and validators where useful.

### L3 — Filesystem

Large media, generated files, thumbnails, and binary artifacts live in controlled cache/temp directories. SQLite stores metadata rather than large blobs whenever practical.

Cache rules:

- bounded size;
- explicit TTL;
- namespace isolation;
- stampede protection for expensive refreshes;
- invalidation/versioning;
- no cache entry is treated as authoritative external state.

## 12. Storage and SQLite

SQLite is the default local persistence layer.

The platform should converge toward a shared infrastructure database for jobs, cache metadata, plugin/runtime metadata, audit records, and other platform state while allowing existing plugin-specific databases to remain during migration.

Required properties:

- WAL where appropriate;
- foreign keys;
- busy timeout;
- numbered migrations;
- short transactions;
- repositories/data-access boundaries;
- integrity checks;
- backup tooling;
- retention policies.

Network calls must not be held open inside database transactions.

## 13. HTTP Service

Plugins use one shared `aiohttp` session/service rather than creating independent sessions for every request.

The HTTP service provides:

- connection pooling;
- total/connect/read timeouts;
- per-host concurrency limits;
- response-size limits;
- safe retries for appropriate transient failures;
- `Retry-After` handling;
- cancellation;
- request timing;
- optional cache integration;
- redaction of sensitive headers/URLs in logs.

HTTP consumers must validate target URLs and avoid accidental unbounded downloads.

## 14. Subprocess Service

All external commands eventually pass through a common SubprocessService.

It provides:

- argv-based execution;
- timeout;
- cancellation cleanup;
- stdout/stderr size caps;
- exit-code classification;
- resource policy;
- safe logging;
- temporary workspace ownership.

`shell=True` is not part of the architecture.

Powerful commands such as FFmpeg, rclone, aria2c, speech tools, and system utilities remain explicitly declared capabilities.

## 15. Media Service

Media processing is centralized instead of being duplicated across plugins.

The service owns:

- per-job temporary workspaces;
- downloads;
- MIME detection;
- FFmpeg invocation;
- transcoding/conversion;
- thumbnails;
- audio extraction;
- cleanup;
- output size limits;
- cancellation.

Each job receives unique input/output paths. Plugins must never identify their output by "newest file in a shared directory".

## 16. Telegram Facade

`ctx.telegram` provides common operations for frequent plugin needs:

- message send/edit/delete;
- media download/upload helpers;
- entity lookup/cache;
- flood-wait handling;
- common formatting;
- bounded retries.

Raw Telethon remains available for advanced cases. The facade is a convenience and policy layer, not a replacement for Telethon.

## 17. AI Gateway

AI is provider-independent and optional.

Conceptual interface:

```text
AI Gateway
 ├── Ollama/local adapter
 ├── llama.cpp/local adapter where useful
 ├── Groq adapter
 ├── other free-provider adapters
 └── fallback/routing policy
```

Providers are configuration, not hard-coded business logic.

AI requests are bounded, cacheable where appropriate, observable, and cancellable.

AI output is untrusted data. It cannot bypass authorization, command policy, filesystem policy, Telegram permissions, or destructive-operation gates.

The userbot must remain useful without AI credentials or external AI access.

## 18. Search and Knowledge

Start with SQLite indexes and FTS5 where justified.

Search layers may grow from:

```text
commands / plugin metadata
→ cached metadata
→ message/document metadata
→ FTS5 text
→ OCR/transcripts
→ optional semantic retrieval
```

Derived search state can be rebuilt and must not become an authority over Telegram or local source data.

## 19. Observability

The platform exposes diagnostics for:

```text
!health
!plugins
!tasks
!jobs
!cache
!stats
!diagnostics
```

Future diagnostics may include:

```text
!db
!http
!media
!ai
```

Observability must distinguish:

- healthy;
- degraded;
- failed;
- disabled;
- not configured.

A successful process start is not equivalent to a healthy plugin platform.

## 20. Error Handling

Internal errors receive correlation IDs.

Users should see concise safe errors such as:

```text
Operation failed [E-7F31]
```

Logs contain the structured traceback and context after secret redaction.

Provider response bodies, filesystem paths, command arguments, tokens, cookies, and session material must not be indiscriminately sent to Telegram.

## 21. Resource-Aware Operation

The target machine is resource constrained. Therefore:

- concurrency is bounded;
- queues are bounded;
- caches have explicit limits;
- media processing is scheduled/on-demand;
- hashing and indexing are incremental;
- AI is optional and resource-aware;
- noisy subprocess output is capped;
- Telegram requests are rate-aware;
- backpressure is preferred over memory exhaustion.

Throughput is never optimized by removing safety limits blindly.

## 22. Security Architecture

The userbot handles high-value credentials and has broad account capabilities. Security is therefore platform infrastructure.

Required properties:

- secrets loaded from environment/configuration, never source;
- session files excluded from Git;
- no secret material in logs/audits;
- proper cryptography for secret storage;
- centralized authorization;
- capability declarations;
- protected administrative commands;
- safe subprocess execution;
- controlled filesystem access;
- explicit network policy where needed;
- audit of security-sensitive actions.

Base64/encoding is never considered encryption.

## 23. Compatibility and Migration

Migration is performed in this order:

1. Build platform service contracts.
2. Keep legacy plugin interfaces working.
3. Migrate highest-risk/shared-infrastructure plugins.
4. Remove duplicate infrastructure.
5. Add tests around behavior.
6. Retire compatibility code only after all consumers migrate.

Existing plugin behavior should not be changed merely for stylistic consistency.

## 24. Explicitly Avoided Initially

Do not introduce these without demonstrated need:

- Redis;
- Kafka;
- RabbitMQ;
- Celery;
- Kubernetes;
- microservices;
- PostgreSQL for internal userbot state;
- ORM-heavy persistence;
- LangChain/LlamaIndex as core infrastructure;
- LiteLLM as a mandatory AI dependency;
- Prometheus/Grafana/OpenTelemetry as mandatory infrastructure;
- automatic hot reload;
- giant generic event buses;
- fake Python sandboxes that claim to isolate arbitrary code.

## 25. Architectural Invariants

1. Telethon remains the Telegram transport authority.
2. The userbot process owns orchestration, not Telegram itself.
3. Plugins cannot silently bypass centralized command/permission rules.
4. Durable work is persisted before it is assumed restart-safe.
5. Required verification precedes successful completion.
6. Secrets never enter source, logs, audits, or AI prompts unnecessarily.
7. External providers are adapters, not architecture authorities.
8. Cache is derived state and bounded.
9. SQLite is the default durable local store.
10. Blocking subprocess work is controlled and cancellable.
11. Media work receives isolated temporary workspaces.
12. AI is optional and advisory.
13. Startup health reports plugin failures honestly.
14. Existing plugins are migrated incrementally.
15. The platform remains usable at ₹0 / $0.
16. Resource usage is bounded and observable.
17. Destructive or high-impact operations require explicit authorization and verification.
18. A component that cannot establish safe scope or ownership must stop rather than guess.

## Architectural Decision

AstraUserbot will evolve as a **single-process, service-oriented modular monolith**: a thin deterministic core with centralized shared services and a large plugin ecosystem. The architecture intentionally extracts infrastructure already duplicated inside plugins instead of performing a mass rewrite.
