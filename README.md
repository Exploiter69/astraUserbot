# AstraUserbot

**A modular, local-first Telegram userbot platform for automation, media, AI, security, productivity, and extensibility.**

| Property | Contract |
|---|---|
| Architecture | Single-process service-oriented modular monolith |
| Language | Python |
| Telegram | Telethon |
| Concurrency | asyncio |
| Persistence | SQLite |
| HTTP | aiohttp |
| Media | FFmpeg + controlled subprocesses |
| AI | Local-first gateway + optional free adapters |
| Cost target | ₹0 / $0 |

## 1. Mission

AstraUserbot is intended to become a reliable personal Telegram automation platform rather than a pile of unrelated command handlers.

The repository already contains roughly 40 functional plugin modules spanning administration, advanced utilities, AI, backup, cryptography, fun, media, network/OSINT, security, stealth, system utilities, and automation.

The architecture therefore focuses on **platform extraction and reliability**, not a destructive rewrite.

## 2. What Astra Provides

### Telegram

Commands, events, message utilities, account automation, moderation, scheduling, notifications, and extensible Telegram workflows.

### Automation

Durable reminders, scheduled messages, maintenance, background processing, retries, and recovery.

### Media

Downloads, FFmpeg processing, conversion, audio/video operations, speech/transcription, thumbnails, and uploads.

### Network

Controlled HTTP/API integrations, DNS/IP utilities, web retrieval, and cached external data.

### AI

Provider-independent chat/summarization/extraction/classification/transcription capabilities, with local models preferred and hosted providers optional.

### Security

Authorization, vault/secret handling, account controls, audit, logging, and explicit privileged boundaries.

### Knowledge

Notes, message cache, FTS5 search, OCR/transcript indexing, and future retrieval capabilities.

## 3. Architecture at a Glance

```text
Telegram / local trigger
          │
          ▼
 Event + Command Router
          │
          ▼
 Authorization + Scope
          │
          ▼
 Application Context
    ┌─────┼───────────────┐
    ▼     ▼               ▼
 Plugins Jobs       Shared Services
          │       ┌────────┼────────────┐
          │       ▼        ▼            ▼
          │     HTTP     Cache      Media/Subprocess
          │       │        │            │
          └───────┴────────┴────────────┘
                          │
                          ▼
                   Storage / AI
                          │
                          ▼
                  Verify + Audit
```

## 4. Core Rules

1. Telethon remains the transport.
2. One process is the default.
3. Plugins consume shared services instead of reinventing them.
4. Durable work is persisted.
5. Ephemeral tasks are supervised.
6. Cache/index state is derived.
7. AI is untrusted/advisory.
8. Authorization is deterministic.
9. Verification is separate from execution.
10. Resource usage is bounded.
11. Secrets never enter source control or ordinary diagnostics.
12. Core operation must remain free.

## 5. Current Audit Findings

The existing codebase was source-audited and identified concrete migration targets:

- ACL and PMGuard both register `.block`/`.unblock`;
- admin help advertises `demote` and `slow` without matching handler branches;
- one vault uses base64 obfuscation while another uses authenticated encryption;
- eval temporarily replaces global `sys.stdout`, which is unsafe under concurrency;
- account archiving can silently swallow persistence errors;
- logger reconstruction state is bounded only in memory;
- PMGuard contact state can become stale until restart;
- AFK can answer repeatedly without per-user cooldown;
- multiple media plugins duplicate FFmpeg/temp/download logic;
- stream output selection can race through shared directories;
- media cleanup is inconsistent on failures;
- rclone/aria2/media subprocess policy is duplicated;
- network plugins independently implement HTTP behavior;
- AI is coupled to provider-specific implementation;
- existing scheduling is not a complete durable job platform.

These findings are engineering inputs, not reasons to discard the plugin ecosystem.

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
which tasks are alive
which jobs are queued/running
how cache is behaving
whether SQLite is healthy
which recent failures occurred
how much resource pressure exists
```

This becomes the purpose of diagnostics such as:

```text
!health
!plugins
!tasks
!jobs
!cache
!stats
!diagnostics
```

## 12. Current Development Stage

**Phase 0 — Baseline and architecture protection: COMPLETE.**

**Phase 1 — Plugin & Command Foundation: COMPLETE.**

- Plugin Manager: complete;
- Command Router: complete;
- Safe Errors: complete;
- TaskSupervisor: complete;
- Gate 1: **28/28 tests passing + compile gate passing**.

**Phase 2 — Shared Runtime Services: IMPLEMENTED.**

- ApplicationContext with explicit service ownership/lifecycle;
- bounded/cancellable SubprocessService;
- shared pooled HttpService with per-host limits, retries and response caps;
- TelegramFacade with bounded FloodWait handling;
- Filesystem/WorkspaceService with safe paths, per-operation workspaces, size limits and orphan cleanup;
- legacy `helpers/shell.py` routed through SubprocessService;
- legacy `helpers/net.py` routed through the ApplicationContext HTTP service;
- runtime startup/shutdown wired through the shared context;
- dedicated Phase 2 service regression suite.

**Next:** run the local Phase 2 gate, then Phase 3 Cache Foundation.

## 13. Definition of Success

Astra succeeds when adding the next 100 useful features does not require inventing another HTTP client, scheduler, cache, temp-file strategy, subprocess wrapper, database pattern, or authorization mechanism.

> **Power belongs at the plugin edge. Reliability belongs in the platform core.**
