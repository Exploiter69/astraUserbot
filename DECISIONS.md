# AstraUserbot — Detailed Architecture Decisions

**Status:** Living ADR record  
**Version:** 2.0  
**Rule:** Accepted decisions constrain implementation until new evidence justifies supersession.

## ADR-001 — Single-Process Modular Monolith

**Status:** Accepted

**Decision:** Keep one primary Python process containing plugins and platform services.

**Why:** The workload is asynchronous, local, and currently manageable without distributed infrastructure.

**Consequences:** Redis, Kafka, RabbitMQ, Celery, Kubernetes, and microservices are not default dependencies. Heavy/untrusted workloads may later move to dedicated processes only with evidence.

## ADR-002 — Telethon Remains Transport

**Decision:** Telethon remains the Telegram transport/client. Common operations may use a facade; raw Telethon remains available.

**Reason:** Existing plugins depend on Telethon semantics and replacing the transport creates unnecessary migration risk.

## ADR-003 — Platform Before Mass Migration

**Decision:** Build shared infrastructure first; migrate plugins incrementally.

**Reason:** The audit found duplicated HTTP, subprocess, media, cache, scheduler, and event behavior. Rewriting all plugins before extracting these services would duplicate effort and increase regression risk.

## ADR-004 — Central Plugin Lifecycle

**Decision:** Plugin discovery, metadata, dependencies, registrations, setup/shutdown, and health are centrally tracked.

**Reason:** Current loader behavior can continue startup despite individual plugin failures. Health must tell the truth.

## ADR-005 — Central Command Router

**Decision:** One router owns command names and aliases. Duplicate registration is a conflict.

**Reason:** ACL and PMGuard currently collide on `.block`/`.unblock`.

**Consequences:** Alias ownership, permission metadata, timing, errors, and diagnostics become queryable platform state.

## ADR-006 — Central Authorization + Capabilities

**Decision:** Use OWNER/ADMIN/TRUSTED/PUBLIC plus capability declarations.

**Reason:** Existing `event.out` behavior provides useful compatibility but is not a complete policy model.

**Consequences:** Authorization is separated from handler implementation and can be tested independently.

## ADR-007 — Durable Jobs in SQLite

**Decision:** Restart-sensitive work uses a SQLite-backed Job Engine.

**Reason:** asyncio tasks disappear with the process.

**Required:** state machine, leases, retry policy, idempotency, verification, cancellation, recovery, audit.

## ADR-008 — TaskSupervisor for Ephemeral Long-Lived Work

**Decision:** TaskGroup for structured bounded work; TaskSupervisor for process-lifetime tasks.

**Reason:** Every long-lived task needs ownership, failure reporting, and shutdown semantics without turning the whole runtime into a giant task registry.

## ADR-009 — SQLite Default Persistence

**Decision:** SQLite remains the primary local durable store.

**Reason:** free, transactional, local, indexed, simple, and already used by the repository.

**Required:** WAL where appropriate, foreign keys, busy timeout, migrations, short transactions, repositories, integrity checks.

## ADR-010 — Three-Tier Cache

**Decision:** L1 memory, L2 SQLite, L3 filesystem where workload justifies it.

**Reason:** Existing plugins already cache data and media independently; a common bounded cache prevents duplicated logic and improves restart behavior.

**Constraint:** no Redis dependency merely to obtain persistence.

## ADR-011 — Shared HTTP Service

**Decision:** One shared aiohttp session/service.

**Reason:** Current network plugins independently implement HTTP behavior, causing inconsistent timeout/retry/size handling.

## ADR-012 — Shared Subprocess Service

**Decision:** External binaries use one controlled subprocess boundary.

**Reason:** FFmpeg, rclone, aria2c, speech, and system utilities need common timeout, cancellation, output and resource policy.

## ADR-013 — MediaService

**Decision:** Media/download/FFmpeg/speech/thumbnail workflows converge on MediaService.

**Reason:** Current media implementations duplicate temp handling and can collide when concurrent jobs choose outputs from shared directories.

## ADR-014 — Provider-Independent AI Gateway

**Decision:** Plugins call an AI gateway rather than provider-specific clients.

**Initial adapters:** local Ollama/llama.cpp where useful, Groq, and other genuinely free providers if configured.

**Reason:** Provider APIs and model IDs change; core feature behavior must remain stable.

## ADR-015 — AI Is Never Authority

**Decision:** AI output is untrusted data.

**Consequences:** deterministic parsing, validation, authorization, scope checks, and verification remain mandatory.

## ADR-016 — Verification Before Completion

**Decision:** Required postconditions must be verified before a job is completed.

**Reason:** executor success is not equivalent to user-visible success.

## ADR-017 — Stable Failure Classes

**Decision:** Retry decisions use stable codes/classes rather than exception-string matching.

**Initial classes:**

```text
TRANSIENT
RATE_LIMITED
TIMEOUT
RESOURCE_LIMIT
INTEGRITY
PERMANENT
CANCELLED
INTERNAL
```

## ADR-018 — Proper Cryptography

**Decision:** Base64/obfuscation is never encryption. SecretStore uses reviewed authenticated encryption and appropriate key derivation.

**Reason:** The repository currently contains a base64 vault and an AES-GCM vault with materially different semantics.

## ADR-019 — Resource Awareness

**Decision:** CPU, RAM, disk, network, Telegram limits, and cache growth are explicit constraints.

**Consequences:** bounded concurrency and backpressure are architectural, not optional optimizations.

## ADR-020 — ₹0/$0 Cost Target

**Decision:** Core operation must remain free.

**Preferred:** Python, Telethon, asyncio, SQLite, aiohttp, FFmpeg/Linux tools, local models.

Optional free hosted APIs may exist but cannot be mandatory foundations.

## ADR-021 — Preserve Existing Behavior

**Decision:** During migration, preserve behavior unless a deliberate defect fix or contract change is recorded.

**Reason:** The plugin ecosystem is valuable existing functionality.

## ADR-022 — P0 Defects Before Feature Expansion

**Confirmed initial defects:**

1. ACL/PMGuard `.block`/`.unblock` collision.
2. Admin advertises `demote`/`slow` without corresponding implementation branches.
3. Base64 vault is not encryption.
4. Global stdout manipulation in eval is unsafe under concurrent invocation.
5. Account archive persistence can fail silently.

Additional reliability work includes retention, stale caches, media output collisions, cleanup leaks, duplicated HTTP/subprocess infrastructure, and provider coupling.

## ADR-023 — Explicit Retention

**Decision:** Every unbounded store has TTL, count, byte, age, or equivalent retention.

**Applies:** account archive, message cache, HTTP cache, media artifacts, logs, audit, job history.

## ADR-024 — Avoid Heavy Frameworks

**Decision:** No large infrastructure dependency without demonstrated need.

**Not default:**

```text
Redis
Kafka
RabbitMQ
Celery
Kubernetes
microservices
PostgreSQL
ORM-heavy persistence
LangChain/LlamaIndex core
LiteLLM mandatory
Prometheus/Grafana mandatory
OpenTelemetry mandatory
APScheduler prerequisite
automatic hot reload
giant generic event bus
```

## ADR-025 — Compatibility Layer Is Temporary

**Decision:** Legacy setup/registration behavior is supported through adapters during migration.

**Exit condition:** all consumers use the new contracts and compatibility code has tests proving it can be removed safely.

## ADR-026 — Tiny Internal Event Bus Only

**Decision:** Telethon remains the event transport. An internal bus may carry genuine application events such as `job.completed` or `plugin.failed`.

**Constraint:** it must not become a second hidden command/event framework.

## ADR-027 — Search Starts with SQLite FTS5

**Decision:** Use ordinary SQLite indexes/FTS5 before vector infrastructure.

**Reason:** local, free, rebuildable, and adequate for initial knowledge/search needs.

## ADR-028 — Existing Plugin Databases Migrate Incrementally

**Decision:** Do not force all existing DBs into one schema immediately.

**Reason:** destructive migration is unnecessary risk. Shared infrastructure moves first; plugin state follows when justified.

## ADR-029 — No Fake Sandbox Claim

**Decision:** Plugins and eval are not treated as security-isolated because they share a Python process.

**Future:** dedicated process/container isolation only for workloads that actually require it.

## ADR-030 — Documentation Is an Engineering Contract

**Decision:** Root architecture documents are canonical. Implementation that contradicts a mandatory contract must either be fixed or accompanied by a new ADR explaining the intentional change.

## Supersession Procedure

To supersede an ADR record:

```text
old decision
new decision
evidence
trade-offs
affected modules
migration plan
compatibility impact
security impact
rollback plan
```

Preference alone is not sufficient evidence.

> **Architecture is allowed to evolve, but it must evolve deliberately and leave an audit trail.**
