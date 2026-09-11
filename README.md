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
- `ROADMAP.md` — canonical implementation sequence;
- `PHASE_7_READINESS.md` — completed Media Platform gate;
- `PHASE_8_READINESS.md` — AI Gateway completion record and final gate.

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
   ┌────────┼───────────────────────────────┐
   ▼        ▼             ▼                 ▼
 Storage   Cache       Supervisors      Shared Services
   │        │             │                 │
   │        ├── L1        ├── Tasks         ├── HTTP
   │        ├── L2        └── Durable       ├── Subprocess
   │        └── L3            Jobs          ├── Telegram
   │                                         ├── Workspace
   └── SQLite WAL / migrations               ├── Media
                                             └── AI Gateway
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
Media Platform
      ↓
AI Gateway
      ↓
Plugin migration batches
      ↓
Feature expansion
```

## 6. Platform Services

The shared service layer now includes:

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
AIService
```

A service is introduced when it removes duplicated infrastructure or establishes a contract needed by multiple features.

## 7. AI Gateway

`AIService` is the only active application boundary for AI features.

```text
.ask / .summarize / .transcribe
              │
              ▼
          AIService
              │
      ┌───────┼───────────┬───────────┐
      ▼       ▼           ▼           ▼
    Groq    Gemini      Ollama     llama.cpp
```

Provider-specific API details, model configuration, response parsing, retries, capability checks and transcription behavior remain inside adapters. The active command plugins do not know the Groq HTTP API.

Local providers are optional; no local model is required on the current host.

## 8. Documentation Set

| File | Role |
|---|---|
| `ARCHITECTURE.md` | Full component architecture and invariants |
| `DATA_MODEL.md` | Persistent state and data ownership |
| `JOB_MODEL.md` | Durable execution state machine |
| `SAFETY_CONTRACT.md` | Mandatory safety and side-effect rules |
| `PRODUCTION_BOUNDARY.md` | Runtime and external-system boundaries |
| `DECISIONS.md` | Accepted architecture decisions |
| `ROADMAP.md` | Canonical implementation sequence |
| `PHASE_8_READINESS.md` | AI Gateway completion and gate contract |

These files are the root engineering specification. Code should conform to them; intentional deviations require a recorded decision.

## 9. Migration Philosophy

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

## 10. Zero-Cost Architecture

The foundation uses free/open-source or already available components:

- Python;
- Telethon;
- asyncio;
- SQLite;
- aiohttp;
- FFmpeg/Linux tools;
- optional local Ollama/llama.cpp;
- optional genuinely free hosted AI providers.

No paid AI SDK, hosted service, or infrastructure is a required dependency.

## 11. Security Position

Astra is a privileged process. Plugins are not security-isolated from one another.

The platform therefore uses:

- centralized authorization;
- capability declarations;
- secret separation;
- safe subprocess boundaries;
- filesystem policy;
- HTTP limits;
- bounded AI execution;
- auditability;
- explicit destructive-operation contracts.

Eval is privileged and is not represented as a sandbox.

AI output is untrusted data and cannot authorize privileged actions.

## 12. Operational Model

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

## 13. Current Development Stage

**Phase 1 — Plugin & Command Foundation: COMPLETE.**

- Plugin Manager;
- Command Router;
- Safe Errors;
- TaskSupervisor;
- Gate 1 passed.

**Phase 2 — Shared Runtime Services: COMPLETE.**

- ApplicationContext;
- bounded/cancellable SubprocessService;
- shared pooled HttpService;
- TelegramFacade;
- WorkspaceService;
- runtime lifecycle integration;
- Phase 2 regression suite passed.

**Phase 3 — Cache Foundation: COMPLETE.**

- bounded L1 memory cache;
- persistent L2 SQLite cache;
- filesystem L3 artifacts;
- namespaces/versioning;
- invalidation/cleanup;
- stampede protection;
- diagnostics;
- Gate 3: 49/49 tests passed.

**Phase 4 — Storage & Migration Foundation: COMPLETE.**

- canonical platform SQLite database;
- deterministic migrations/checksums;
- WAL/foreign keys/busy timeout/integrity checks;
- verified backup/restore;
- platform persistence regression coverage.

**Phase 5 — Durable Job Engine: COMPLETE.**

- durable job persistence;
- lifecycle state machine;
- `UNCERTAIN` execution state;
- worker leasing/heartbeat;
- explicit uncertain replay reconciliation;
- bounded retries/backoff;
- idempotency;
- cancellation;
- parent/child jobs;
- progress/verification;
- attempts/events;
- resource class/priority;
- supervised worker loop.

**Phase 6 — Confirmed P0 Reliability Fixes: COMPLETE.**

- command ownership conflict fixed;
- admin gaps fixed;
- encrypted SecretStore;
- eval isolation/bounds;
- archive/logger retention;
- PMGuard refresh;
- AFK cooldown;
- isolated media paths;
- shared subprocess migration;
- uncertain-job recovery tests.

**Pre-Phase-7 Gate:** 75/75 tests passed + compile validation passed.

**Phase 7 — Media Platform: COMPLETE.**

- `MediaService` is the authoritative media boundary;
- unique operation workspaces;
- input/output/workspace bounds;
- bounded media concurrency;
- explicit FFmpeg argv;
- FFprobe verification;
- deterministic download manifests;
- TTS/download output verification;
- rclone operation allowlist;
- all seven media consumers migrated;
- cleanup in failure paths.

**Gate 7:** **81/81 tests passed, 0 failures, 0 errors, compile validation passed.**

**Phase 8 — AI Gateway: IMPLEMENTATION COMPLETE.**

- `AIService` registered in `ApplicationContext`;
- Groq adapter;
- Gemini adapter;
- optional Ollama adapter;
- optional llama.cpp adapter;
- provider-neutral chat/summarize/extract/classify/transcribe APIs;
- bounded input/output/audio/concurrency;
- shared HttpService transport;
- cancellation and capability checks;
- active `.ask`, `.summarize`, `.transcribe` command adapters migrated to `plugins/ai_gateway`;
- legacy Groq command modules quarantined from discovery;
- AI remains non-authoritative;
- no paid AI dependency introduced;
- 14 dedicated AI gateway regression tests added.

**Gate 8:** implementation complete; final local verification is the only remaining release check. Expected full suite: **95 tests**.

**Next:** Phase 9 — Plugin Migration Program.

## 14. Definition of Success

Astra succeeds when adding the next 100 useful features does not require inventing another HTTP client, scheduler, cache, temp-file strategy, subprocess wrapper, database pattern, or authorization mechanism.

> **Power belongs at the plugin edge. Reliability belongs in the platform core.**
