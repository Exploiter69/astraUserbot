# AstraUserbot

A modular, local-first Telegram userbot platform built with **Python + Telethon + asyncio**, designed to grow from a large plugin collection into a reliable engineering platform.

**Cost target:** ₹0 / $0  
**Architecture:** single-process modular monolith  
**Transport:** Telethon  
**Persistence:** SQLite  
**Runtime:** asyncio

## What AstraUserbot Is

AstraUserbot is more than a command collection. It provides a platform for:

- Telegram automation;
- modular plugins;
- durable scheduled work;
- media processing;
- HTTP/API integrations;
- local and optional hosted AI;
- security and account controls;
- search and knowledge features;
- backups and maintenance;
- operational diagnostics;
- reusable shared infrastructure.

The repository already contains a broad plugin ecosystem. The current architectural effort is to make that ecosystem reliable, observable, and easier to extend without rewriting everything.

## Architecture

```text
                    Telegram
                       │
                       ▼
                Event / Command Router
                       │
                       ▼
                Authorization Layer
                       │
                       ▼
               Application Context
          ┌────────────┼─────────────┐
          ▼            ▼             ▼
      Plugins      Job Engine    Shared Services
                       │         ┌────┼────┬────┐
                       │         ▼    ▼    ▼    ▼
                       │        HTTP Cache Media AI
                       │
                       ▼
                 Verification/Audit
```

The platform is intentionally a **service-oriented modular monolith**, not a distributed system.

## Core Principles

1. **Telethon remains the Telegram transport.**
2. **Plugins remain modular and migrate incrementally.**
3. **Shared infrastructure is centralized.**
4. **Durable work is persisted.**
5. **Asyncio tasks are not treated as durable jobs.**
6. **AI is advisory, never authoritative.**
7. **Secrets never enter source, logs, or audits.**
8. **Caches and indexes are derived state.**
9. **Verification is distinct from execution success.**
10. **Resource usage is bounded.**
11. **Core functionality remains free.**
12. **High-impact operations require explicit authorization.**

## Current Plugin Surface

The existing repository contains approximately 40 functional plugin modules across areas including:

- administration;
- advanced utilities;
- AI;
- backup;
- cryptography;
- fun;
- media;
- media operations;
- network/OSINT;
- security;
- stealth;
- system utilities;
- system operations.

The platform is built around this existing surface rather than discarding it.

## Confirmed Engineering Priorities

The repository audit identified several high-priority areas:

- duplicate `.block` / `.unblock` command ownership;
- advertised but missing admin command branches;
- inconsistent vault/security semantics;
- concurrent global stdout manipulation in eval;
- silent account-archiver persistence failures;
- stale in-memory caches;
- duplicated media/subprocess infrastructure;
- unsafe shared-directory output selection;
- inconsistent temporary-file cleanup;
- provider-specific AI coupling;
- independent HTTP implementations;
- incomplete durable scheduling semantics.

These findings are reflected in the roadmap and architecture documents.

## Documentation

| Document | Purpose |
|---|---|
| `ARCHITECTURE.md` | Canonical system architecture and component boundaries |
| `DATA_MODEL.md` | Persistent state, cache, jobs, audit, and derived-data model |
| `JOB_MODEL.md` | Durable job lifecycle, retries, leases, recovery, and verification |
| `SAFETY_CONTRACT.md` | Mandatory safety and side-effect rules |
| `PRODUCTION_BOUNDARY.md` | Telegram, filesystem, network, database, and runtime boundaries |
| `DECISIONS.md` | Architecture Decision Record (ADR) history |
| `ROADMAP.md` | Canonical implementation sequence |

## Implementation Sequence

```text
Baseline
  ↓
Plugin / Command Foundation
  ↓
Shared Runtime Services
  ↓
Cache
  ↓
Storage / Persistence
  ↓
Durable Jobs
  ↓
High-Risk Plugin Fixes
  ↓
Media Platform
  ↓
AI Gateway
  ↓
Plugin Migration
  ↓
Search / Knowledge
  ↓
Observability
  ↓
Feature Expansion
  ↓
Performance / Maturity
```

## Zero-Cost Requirement

AstraUserbot is designed around a hard ₹0 / $0 cost target.

Preferred infrastructure:

- Python;
- Telethon;
- asyncio;
- SQLite;
- aiohttp;
- FFmpeg and standard Linux tools;
- local Ollama/llama.cpp where useful;
- existing machine resources;
- optional genuinely free provider adapters.

Paid services are never mandatory foundations.

## Development Philosophy

### Do not rewrite blindly

Existing plugins contain useful working behavior. Platform services should be introduced first, then plugins migrated in batches with regression tests.

### Do not over-engineer

Astra does not need a miniature cloud platform to run a Telegram userbot. New infrastructure must solve a measured problem.

### Do not hide failures

Plugin setup failures, task crashes, job failures, verification failures, and dependency problems must be observable.

### Do not confuse automation with authority

The system can automate aggressively within explicit boundaries, but no model, plugin, cache, or background task is allowed to invent permission.

## Security

Runtime credentials and Telegram session state are local secrets. They must never be committed to GitHub.

Use `.env.example` for placeholders and keep actual `.env`, session files, databases, logs, and generated artifacts outside source control as appropriate.

## Status

The project is in the **platform architecture and reliability foundation** stage. The immediate implementation target is Phase 1 of `ROADMAP.md`: plugin lifecycle, command routing, startup health, safe error handling, and task supervision.

## Guiding Principle

> **Make AstraUserbot powerful by capability, reliable by architecture, observable by default, and cheap enough to run at ₹0.**
