# AstraUserbot

A modular, service-oriented Telegram userbot platform designed for reliability, explicit safety boundaries, durable background work, and zero-cost operation.

## 1. Project Position

AstraUserbot is being developed as a long-lived platform rather than a collection of independent command scripts.

The repository began from an existing feature-rich userbot. The current engineering work therefore prioritizes **platform extraction, correctness, safety, and compatibility** before broad feature expansion.

## 2. Core Principles

1. Telegram remains the transport layer, not the application architecture.
2. Plugins provide capabilities; shared services own infrastructure.
3. The platform must make command/plugin collisions explicit.
4. Background work must be supervised; restart-sensitive work must become durable jobs.
5. SQLite is the default durable local store.
6. Cache state is never treated as authoritative external state.
7. AI providers are replaceable and AI output is never authority.
8. Side effects require explicit authorization and bounded execution.
9. User-facing errors must not expose secrets, paths, provider responses, or tracebacks.
10. Resource usage must be bounded.
11. Existing behavior is preserved during migration unless a defect is intentionally corrected.
12. No paid dependency is required for the platform to operate.

## 3. Architecture Documents

Read these before making structural changes:

- `ARCHITECTURE.md` — complete component architecture;
- `DATA_MODEL.md` — data ownership and persistence model;
- `JOB_MODEL.md` — durable job lifecycle;
- `SAFETY_CONTRACT.md` — mandatory safety rules;
- `PRODUCTION_BOUNDARY.md` — authority and runtime boundaries;
- `DECISIONS.md` — accepted architecture decisions;
- `ROADMAP.md` — canonical implementation sequence.

## 4. Current Platform Shape

```text
Telegram / external systems
            │
            ▼
       Command Router
            │
            ▼
      ApplicationContext
            │
   ┌────────┼────────────────────────────┐
   ▼        ▼             ▼              ▼
 Storage   Cache       Supervisors    Shared Services
   │        │             │              │
   │        ├── L1        ├── Tasks      ├── HTTP
   │        ├── L2        └── Durable    ├── Subprocess
   │        └── L3            Jobs       ├── Telegram
   │                                     └── Workspace
   └── SQLite WAL / migrations
```

## 5. Platform Before Plugins

The implementation order is deliberate:

```text
Baseline protection
      ↓
Plugin / command foundation
      ↓
Shared runtime services
      ↓
Cache foundation
      ↓
Storage / migration foundation
      ↓
Durable jobs
      ↓
Confirmed reliability fixes
      ↓
Plugin migration batches
      ↓
Feature expansion
```

## 6. Platform Services

The target shared services are:

```text
ApplicationContext
PluginManager
CommandRouter
Authorization/Policy
TaskSupervisor
JobEngine
Storage/Repositories
CacheService
HttpService
SubprocessService
Filesystem/WorkspaceService
TelegramFacade
MediaService
AI Gateway
SearchService
AuditService
DiagnosticsService
```

A service is introduced when it removes duplicated infrastructure or establishes a contract needed by multiple features.

## 7. Documentation Set

| File | Role |
|---|---|
| `ARCHITECTURE.md` | Full component architecture and invariants |
| `DATA_MODEL.md` | Persistent state and data ownership |
| `JOB_MODEL.md` | Durable execution state machine |
| `SAFETY_CONTRACT.md` | Mandatory safety and side-effect rules |
| `PRODUCTION_BOUNDARY.md` | Runtime and external-system boundaries |
| `DECISIONS.md` | Accepted architecture decisions |
| `ROADMAP.md` | Canonical implementation sequence |

These files are the root engineering specification. Code should conform to them; intentional deviations require a recorded decision.

## 8. Migration Philosophy

```text
Protect baseline
    ↓
Build platform contract
    ↓
Build shared services
    ↓
Fix confirmed P0 defects
    ↓
Migrate plugins in batches
    ↓
Add regression tests
    ↓
Expand capabilities
    ↓
Measure and optimize
```

No mass rewrite occurs merely to make code look uniform.

## 9. Zero-Cost Architecture

The foundation uses free/open-source or already available components:

- Python;
- Telethon;
- asyncio;
- SQLite;
- aiohttp;
- FFmpeg/Linux tools;
- local Ollama/llama.cpp where useful.

Hosted AI/API adapters may be used only when genuinely free and configured by the user. No paid service is a required dependency.

## 10. Security Position

Astra is a privileged process. Plugins are not security-isolated from one another.

The platform therefore uses:

- centralized authorization;
- capability declarations;
- secret separation;
- safe subprocess boundaries;
- filesystem policy;
- HTTP limits;
- auditability;
- explicit destructive-operation contracts.

Eval is privileged and is not represented as a sandbox.

## 11. Operational Model

A healthy Astra runtime should be able to explain:

```text
which plugins loaded
which commands exist
which background tasks are running
which durable jobs are queued/running/failed
which cache namespaces are consuming resources
which external operations are active
which failures are recent
```

Diagnostics are therefore part of the platform design, not an afterthought.

## 12. Current Development Stage

**Phase 1 — Plugin & Command Foundation: COMPLETE.**

- Plugin Manager: complete;
- Command Router: complete;
- Safe Errors: complete;
- TaskSupervisor: complete;
- Gate 1: **28/28 tests passing + compile gate passing**.

**Phase 2 — Shared Runtime Services: COMPLETE.**

- ApplicationContext with explicit service ownership/lifecycle;
- bounded/cancellable SubprocessService;
- shared pooled HttpService with per-host limits, retries and response caps;
- TelegramFacade with bounded FloodWait handling;
- Filesystem/WorkspaceService with safe paths, per-operation workspaces, size limits and orphan cleanup;
- legacy `helpers/shell.py` routed through SubprocessService;
- legacy `helpers/net.py` routed through the ApplicationContext HTTP service;
- runtime startup/shutdown wired through the shared context;
- dedicated Phase 2 service regression suite;
- Gate 2: **37/37 tests passing + compile gate passing**.

**Phase 3 — Cache Foundation: COMPLETE.**

- bounded L1 in-memory LRU cache;
- persistent L2 SQLite cache with WAL, TTL and access metadata;
- filesystem L3 artifact cache with SQLite metadata;
- namespace and version isolation;
- explicit invalidation and cleanup;
- entry and byte limits at every tier;
- safe JSON value serialization;
- per-key stampede protection through `get_or_set()`;
- cache statistics and diagnostics;
- atomic artifact writes and orphan-safe artifact metadata handling;
- dedicated cache regression coverage;
- ApplicationContext lifecycle integration;
- Gate 3: **49/49 full regression tests passing**.

**Phase 4 — Storage & Migration Foundation: COMPLETE.**

- canonical platform SQLite database;
- deterministic migration runner with schema versions and checksums;
- WAL, foreign keys, busy timeout and integrity checks;
- transactional migration execution;
- platform tables for plugins, commands, jobs, attempts, events, leases and audit records;
- verified SQLite backup/restore support;
- ApplicationContext integration through `StorageService`;
- dedicated Phase 4/5 storage regression coverage;
- Gate 4/5 validation included in the combined 64-test suite.

**Phase 5 — Durable Job Engine: COMPLETE.**

- durable job persistence;
- canonical `QUEUED/RUNNING/PAUSED/VERIFYING/COMPLETED/FAILED/CANCELLED` states;
- worker leasing and heartbeat;
- expired-lease recovery;
- bounded retry/backoff and stable failure codes;
- idempotency keys;
- cancellation;
- parent/child job relationship support;
- progress tracking;
- verification state;
- attempt and event history;
- resource class and priority metadata;
- handler registration and supervised worker loop;
- ApplicationContext lifecycle integration;
- no-handler and unexpected-failure containment.

**Phase 6 — Confirmed P0 Reliability Fixes: IMPLEMENTED; gate pending local verification.**

- `.block` / `.unblock` now have one command owner;
- advertised admin `demote` and `slow` commands are implemented;
- security vault now uses AES-256-GCM SecretStore with an external master key and transparent legacy base64 migration;
- eval output capture is serialized, isolated from module globals, bounded, and timeout-controlled;
- account archiver now surfaces persistence failures and has age/count retention plus orphan pruning;
- logger has bounded L1 plus persistent bounded/retained message cache;
- PMGuard refreshes contacts periodically instead of caching only at startup;
- AFK auto-replies have a bounded per-sender cooldown;
- stream downloads use unique workspaces and deterministic cleanup;
- media temporary files clean up on failure paths;
- rclone/aria2 use the shared SubprocessService when the runtime context is available;
- Phase 6 regression coverage covers command ownership, admin surface, secrets, eval concurrency, retention, cooldowns, media isolation, cleanup and subprocess routing.

**Gate 6:** run the full test and compile gate locally. No bot restart is required for test-only verification.

## 13. Definition of Success

Astra succeeds when adding the next 100 useful features does not require inventing another HTTP client, scheduler, cache, temp-file strategy, subprocess wrapper, database pattern, or authorization mechanism.

> **Power belongs at the plugin edge. Reliability belongs in the platform core.**
