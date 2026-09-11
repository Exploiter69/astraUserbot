# AstraUserbot

A modular, service-oriented Telegram userbot platform designed for reliability, explicit safety boundaries, durable background work, and zero-cost operation.

## 1. Project Position

AstraUserbot is being developed as a long-lived platform rather than a collection of independent command scripts.

The repository began from an existing feature-rich userbot. The engineering work therefore prioritizes **platform extraction, correctness, safety, compatibility, observability, and measured expansion**.

## 2. Core Principles

1. Telegram remains the transport layer, not the application architecture.
2. Plugins provide capabilities; shared services own infrastructure.
3. The platform must make command/plugin collisions explicit.
4. Background work must be supervised; restart-sensitive work must become durable jobs.
5. SQLite is the default durable local store.
6. Cache and search state are derived and rebuildable.
7. AI providers are replaceable and AI output is never authority.
8. Side effects require explicit authorization and bounded execution.
9. User-facing errors and diagnostics must not expose secrets.
10. Resource usage must be bounded.
11. Existing behavior is preserved during migration unless a defect is intentionally corrected.
12. No paid dependency is required for the platform to operate.
13. Isolation is never claimed unless it is actually enforced.

## 3. Architecture Documents

Read these before making structural changes:

- `ARCHITECTURE.md` — complete component architecture;
- `DATA_MODEL.md` — data ownership and persistence model;
- `JOB_MODEL.md` — durable job lifecycle;
- `SAFETY_CONTRACT.md` — mandatory safety rules;
- `PRODUCTION_BOUNDARY.md` — authority and runtime boundaries;
- `DECISIONS.md` — accepted architecture decisions;
- `ROADMAP.md` — canonical implementation sequence;
- `PHASE_9_READINESS.md` — plugin migration contract;
- `PHASE_10_15_READINESS.md` — search, observability, expansion, performance, isolation and maturity verification;
- `PLUGIN_SDK.md` — plugin API contract;
- `COMPATIBILITY.md` — version policy;
- `DISASTER_RECOVERY.md` — recovery procedure;
- `RELEASE_CHECKLIST.md` — release gate.

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
   ┌────────┼─────────────────────────────────────────┐
   ▼        ▼             ▼                           ▼
 Storage   Cache       Supervisors              Shared Services
   │        │             │                           │
   │        ├── L1        ├── TaskSupervisor          ├── HTTP
   │        ├── L2        └── Durable JobEngine       ├── Subprocess
   │        └── L3                                    ├── Telegram
   └── SQLite WAL / migrations                         ├── Workspace
                                                       ├── Media
                                                       ├── AI
                                                       ├── Search
                                                       ├── Metrics
                                                       ├── Feature Flags
                                                       └── Isolation Policy
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
Search & Knowledge
      ↓
Observability
      ↓
Feature expansion
      ↓
Performance
      ↓
Optional isolation assessment
      ↓
Platform maturity
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
SearchService
MetricsService
FeatureFlagService
IsolationService
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
        ┌─────┴─────┐
        ▼           ▼
      Groq        Gemini
```

Provider-specific API details, model configuration, response parsing, retries, capability checks and transcription behavior remain inside adapters. The active command plugins do not know provider HTTP APIs.

No local model is required on the current host. No paid AI provider is required by the architecture.

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
| `PHASE_9_READINESS.md` | Plugin migration gate |
| `PHASE_10_15_READINESS.md` | Final roadmap-phase implementation and verification contract |
| `PLUGIN_SDK.md` | Plugin API contract |
| `COMPATIBILITY.md` | Version and migration policy |
| `DISASTER_RECOVERY.md` | Backup, restore and recovery procedure |
| `RELEASE_CHECKLIST.md` | Release verification gate |

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
    ↓
Harden release and recovery
```

No mass rewrite occurs merely to make code look uniform.

## 10. Zero-Cost Architecture

The foundation uses free/open-source or already available components:

- Python;
- Telethon;
- asyncio;
- SQLite/FTS5;
- aiohttp;
- FFmpeg/Linux tools;
- Groq/Gemini only when genuinely free access is configured;
- existing local operating-system tooling.

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
- explicit destructive-operation contracts;
- explicit isolation policy rather than fake sandbox claims.

Eval is privileged and is not represented as a sandbox.

AI output is untrusted data and cannot authorize privileged actions.

## 12. Operational Model

A healthy Astra runtime should be able to explain:

```text
which plugins loaded
which commands exist
which background tasks are running
which durable jobs are queued/running/uncertain/failed
which cache namespaces are consuming resources
which search indexes are ready
which failures are recent
which resources are under pressure
```

Diagnostics are therefore part of the platform design, not an afterthought.

## 13. Current Development Stage

**Phases 1–8: COMPLETE.**

Plugin lifecycle, command ownership, safe errors, task supervision, shared runtime services, bounded cache, durable SQLite storage, JobEngine with explicit `UNCERTAIN` recovery, confirmed P0 reliability fixes, MediaService, and the provider-independent Groq/Gemini AI Gateway are implemented and gated.

**Phase 9 — Plugin Migration Program: PASS.**

The existing network/OSINT, media, OCR, system, backup and active AI consumers were moved onto the shared service boundaries. The local full suite and Phase 9 gate both passed before the Phase 10–15 implementation pass began.

**Phases 10–15 — IMPLEMENTATION COMPLETE; FINAL LOCAL VERIFICATION PENDING.**

Implemented in the current main branch:

- Phase 10: rebuildable SQLite FTS5 SearchService, plugin/command/document/message indexing, `.search`, `.reindex`;
- Phase 11: `.health`, `.plugins`, `.tasks`, `.jobs`, `.cache`, `.stats`, `.diagnostics` and bounded secret-redacted reports;
- Phase 12: additional shared-service developer/web/feed utilities while preserving the existing broad plugin ecosystem;
- Phase 13: bounded MetricsService, command latency/failure measurement, resource snapshots, queue-depth visibility and benchmark tooling;
- Phase 14: explicit optional isolation policy with no false sandbox claim;
- Phase 15: versioned Plugin SDK, compatibility policy, persistent feature flags, migration/backup/self-test/benchmark tooling, disaster recovery and release checklist.

The implementation is deliberately **not** labeled Phase 10–15 PASS until the owner runs the local verification contract on the real machine.

## 14. Verification Contract

```bash
python -m unittest discover -s tests -v
python -m unittest tests.test_phase10_15_gate -v
python -m compileall -q .
python -m tools.astra_platform selftest
python -m tools.astra_platform benchmark
python -m tools.astra_platform migrate
```

Then perform a controlled startup/shutdown smoke test and inspect `.health`, `.plugins`, `.diagnostics`, `.reindex`, and backup/restore behavior.

## 15. Definition of Success

Astra succeeds when adding the next 100 useful features does not require inventing another HTTP client, scheduler, cache, temp-file strategy, subprocess wrapper, database pattern, search index, metrics path, or authorization mechanism.

> **Power belongs at the plugin edge. Reliability belongs in the platform core.**
