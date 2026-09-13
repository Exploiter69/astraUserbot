# AstraUserbot — Detailed Architecture Specification

**Status:** Canonical architectural contract  
**Version:** 2.1  
**Scope:** Core runtime, plugin platform, Telegram, persistence, jobs, cache, media, AI, search, observability, security, testing, release and recovery  
**Cost target:** ₹0 / $0

> **Current implementation note:** this document describes the architecture as it is implemented and verified on the current release line. Where an older section uses future/deferred language, the current implementation rules below take precedence.

## Current implementation status

The platform foundation and hardening program are implemented. The owner-host verification baseline is:

- plugin ecosystem: deterministic discovery, metadata, lifecycle, ownership, quarantine and controlled enable/disable;
- command ingress: outgoing-only central command registration, with a small explicit allowlist of direct incoming security/watchers;
- runtime: `ApplicationContext` with shared services and bounded lifecycle shutdown;
- jobs: durable SQLite JobEngine with leases, fencing, retries, idempotency keys, retention and explicit `UNCERTAIN` recovery;
- storage: WAL, migrations/checksums, integrity checks, transaction rollback, concurrent-writer coverage and verified backup/restore;
- media: bounded Telegram downloads, duration/disk limits, managed workspaces, artifact verification and isolated decoder/transform execution;
- isolation: real Bubblewrap for classified child workloads; required isolation fails closed when unavailable;
- AI: provider-independent gateway with Groq/Gemini remote adapters and loopback-only Ollama, bounded input/output/concurrency/timeouts, remote request budgets and tool/function-call rejection;
- search: SQLite FTS5 with rebuildable derived indexes;
- observability: health/plugins/tasks/jobs/cache/stats/diagnostics plus operator status/attention views;
- release/recovery: compatibility policy, disaster recovery, upgrade procedure, failure-mode matrix, release checklist and production acceptance gate.

Current verified active-plugin inventory: **41 active, 4 intentionally quarantined**. The quarantined modules are `plugins.ai.ask`, `plugins.ai.groq_client`, `plugins.ai.summarize`, and `plugins.ai.transcribe`.

## 1. Purpose

AstraUserbot is a long-lived Telegram userbot platform built with Python, Telethon, and asyncio. The goal is not to replace its ecosystem with a framework; it is to provide deterministic contracts around lifecycle, authorization, persistence, execution, verification, recovery and resource use.

The target architecture is a **single-process service-oriented modular monolith**.

## 2. Architectural Invariants

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
15. A release is not production-ready until the automated and manual acceptance contracts pass.
16. Isolation is never claimed unless the reviewed backend actually enforces it.

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
       Storage / Media / AI / Search
                │
                ▼
        Verify + Audit + Report
```

## 4. Runtime Layers

### Layer 0 — Transport
Telethon client/session/event delivery. This layer knows Telegram mechanics, not plugin business rules.

### Layer 1 — Core runtime
Bootstrap, configuration, lifecycle, correlation IDs, error boundaries, task supervision and service ownership.

### Layer 2 — Platform services
Router, authorization, storage, cache, HTTP, subprocess, Telegram facade, media, AI, jobs, audit, search, diagnostics and metrics.

### Layer 3 — Plugins
Feature modules. Plugins consume services and must not recreate shared infrastructure.

### Layer 4 — External systems
Telegram, web APIs, local programs, filesystem, model runtimes and configured storage targets.

## 5. Application Context

`ApplicationContext` is the runtime dependency boundary. It owns process-wide services and closes them in dependency-safe reverse order. Production shutdown is bounded; cancellation-resistant child work cannot indefinitely block service teardown.

Lifecycle:

```text
CREATE → CONFIGURE → OPEN → LOAD PLUGINS → RUN
  → QUIESCE → STOP WORKERS/TASKS → UNLOAD PLUGINS
  → CLOSE SERVICES → DISCONNECT TELEGRAM
```

## 6. Plugin Contract

Plugin metadata vocabulary includes name, version, API version, dependencies, optional dependencies, capabilities/permissions and description. The Plugin Manager owns deterministic discovery, metadata validation, dependency ordering, lifecycle, command/event ownership, quarantine and bounded setup/shutdown.

Legacy `setup()` plugins remain supported through a compatibility adapter. Runtime enable/disable is lifecycle-controlled and dependency-aware; it does not silently rewrite persistent configuration.

## 7. Command Router

The router is the registration authority. Each command record contains canonical name, aliases, owner plugin, handler, permission/capability metadata, side-effect classification, description and registration source.

Duplicate active command/alias ownership is rejected deterministically. The historical ACL/PMGuard `.block`/`.unblock` collision is resolved: ACL is the sole owner.

Current command ingress is intentionally outgoing-only. A small explicit allowlist of direct incoming watchers exists for security/account behaviors that are not ordinary owner commands. The behavioral audit verifies that allowlist.

## 8. Request Execution Contract

Side-effecting requests use:

```text
REQUEST → VALIDATE → AUTHORIZE → PLAN → EXECUTE → VERIFY → AUDIT → REPORT
```

Unknown scope, permission or completion stops the operation or enters explicit reconciliation.

## 9. Authorization and Capabilities

Policy levels are `OWNER`, `ADMIN`, `TRUSTED`, `PUBLIC`. Capabilities describe intended access, but capability metadata is not itself authorization. Protected actions must pass the applicable policy boundary.

## 10. Task Supervision

Long-lived process-local tasks are owned by `TaskSupervisor` with lifecycle metadata, bounded shutdown and bounded failure history. Restart-sensitive work uses the durable JobEngine instead.

## 11. Shared HTTP Service

HTTP integrations use one shared `aiohttp` session with bounded timeout, concurrency, response size, redirect, retry and cancellation policy. Arbitrary URL features must apply deliberate scheme/target policy.

## 12. Subprocess Service

Managed external commands use argv execution through the shared subprocess service with timeout, cancellation, output, environment and resource policy. Shell interpolation is prohibited.

Classified high-risk child workloads additionally cross `IsolationService` and execute under the reviewed Bubblewrap boundary.

## 13. Filesystem and Workspace Service

Canonical roots distinguish source, data, cache, temporary and export/protected paths. Media/download jobs receive unique managed workspaces. Cleanup occurs on success, failure and cancellation; orphan cleanup is part of maintenance.

## 14. Cache Architecture

L1 memory, L2 SQLite metadata and L3 filesystem artifacts are bounded, namespaced and disposable. Cache loss never implies authoritative data loss.

## 15. Storage Architecture

SQLite remains the durable platform store. The implementation uses WAL where appropriate, foreign keys, busy timeout, numbered/checksummed migrations, short transactions, integrity checks, bounded queries and verified backup/restore. Network calls are not held inside DB transactions.

Plugin-specific databases remain supported until migration is proven safe.

## 16. Durable Job Engine

Durable work uses explicit state transitions and SQLite persistence:

```text
QUEUED → RUNNING → VERIFYING → COMPLETED
             ├→ QUEUED (retry)
             ├→ UNCERTAIN
             ├→ FAILED
             └→ CANCELLED
```

Jobs have bounded payload/result/error data, leases and attempt fencing, retry/backoff, idempotency support, retention and operator-visible failure state. Lease expiry or interrupted active work is never treated as success.

## 17. Media Architecture

`MediaService` is the common boundary for Telegram download preparation, MIME/duration/size checks, FFmpeg/ffprobe, conversion, artifact verification, upload preparation and cleanup. FFmpeg/ffprobe and OCR use real isolated child execution. Network-requiring download/rclone/TTS operations retain explicit non-isolated network policy.

A job must never infer its result by scanning a shared directory for the newest file. Artifact ownership and validation are explicit.

## 18. Telegram Facade

`ctx.telegram` centralizes common send/edit/delete, entity lookup, upload/download preparation and common policy. Advanced plugins may use raw Telethon where necessary, but shared infrastructure remains centralized.

## 19. AI Gateway

The active AI boundary is provider-independent `AIService`. Supported architecture includes remote Groq/Gemini adapters and loopback-only local Ollama. Provider selection, model validation, request budgets, concurrency, timeouts, response bounds and malformed-response handling are centralized.

Tool/function calls are rejected; the gateway has no arbitrary tool execution surface. AI output is data and cannot authorize or perform privileged mutations.

## 20. Search

SQLite FTS5 provides rebuildable derived search state for plugin metadata, commands and supported documents/messages/OCR/transcripts. Search state never outranks authoritative records.

## 21. Observability

Operator views include `.health`, `.plugins`, `.tasks`, `.jobs`, `.cache`, `.stats`, `.diagnostics`, `.status` and `.ops`. Diagnostics expose useful state, counts, timing and classified failures while redacting secrets.

## 22. Error Model

Stable classes include `AUTH_DENIED`, `INVALID_INPUT`, `NOT_FOUND`, `CONFLICT`, `RATE_LIMITED`, `TIMEOUT`, `NETWORK_ERROR`, `RESOURCE_LIMIT`, `INTEGRITY_FAILED`, `CANCELLED`, `UNSUPPORTED` and `INTERNAL_ERROR`. User-facing errors are concise; detailed logs remain redacted.

## 23. Security Architecture

Plugins are same-process code and therefore not memory-isolated trust boundaries. Privileged operations require explicit policy and bounded scope. Secret storage uses authenticated encryption. Eval and classified media/decoder workloads use the reviewed Bubblewrap isolation boundary rather than a fake Python sandbox.

## 24. Resource Model

Every subsystem uses explicit bounds for concurrency, output, payloads, media size/duration, disk use, cache, DB work, jobs and AI context/output. Backpressure is preferred over unbounded queues or memory growth.

## 25. Plugin Migration Strategy

Migration is batch-based and behavior-preserving:

```text
Foundation → Security/Admin → Network/HTTP
→ Media/Subprocess → System/Automation → AI/Advanced
```

Each migration requires shared-service usage, regression coverage, cleanup/failure verification and documentation updates.

## 26. Testing Architecture

Test layers include pure unit, service contract, SQLite migration/repository, plugin registration, command conflict, task/job lifecycle, HTTP/subprocess policy, media workspace, plugin integration and safe end-to-end smoke tests. The canonical release gate composes the relevant suites and audits.

## 27. Release and Recovery Contract

The release system is documented in:

- `RELEASE_CHECKLIST.md` — release checklist;
- `PRODUCTION_ACCEPTANCE.md` — automated and manual production gate;
- `OPERATIONS_RUNBOOK.md` — day-to-day operation;
- `UPGRADE_PROCEDURE.md` — controlled upgrade/rollback;
- `DISASTER_RECOVERY.md` — backup/restore/recovery;
- `FAILURE_MODE_MATRIX.md` — failure classification and first response;
- `COMPATIBILITY.md` — version and migration policy.

The current release version is recorded in `VERSION`. A Git tag is created only after acceptance passes.

## 28. Explicitly Rejected as Defaults

Do not introduce Redis, Kafka, RabbitMQ, Celery, Kubernetes, microservices, Postgres, ORM-heavy persistence, LangChain/LlamaIndex core, mandatory LiteLLM, mandatory Prometheus/Grafana/OTel, automatic hot reload or a giant event bus without evidence.

## 29. Definition of Architectural Completion

The platform is architecturally complete for the current release line when plugin lifecycle is observable, command conflicts are deterministic, shared services have stable contracts, durable jobs have explicit recovery semantics, cache/search are derived and bounded, storage is migration-driven and recoverable, media workloads are bounded/isolated where required, AI is provider-independent and advisory, diagnostics are secret-safe, and release/recovery gates are executable and documented.

> **AstraUserbot should be powerful at the plugin edge and boring at the infrastructure core: deterministic, bounded, observable, recoverable, and free to operate.**
