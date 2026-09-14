# AstraUserbot

A modular, service-oriented Telegram userbot platform designed for reliability, explicit safety boundaries, durable background work, observable operations and zero-cost operation.

**Current release:** `1.0.0`  
**Architecture:** single-process Python/asyncio modular monolith  
**Transport:** Telethon  
**Durable store:** SQLite/WAL  
**Cost target:** ₹0 / $0

## Project position

AstraUserbot began as a broad feature-rich userbot. The engineering program extracted shared infrastructure without requiring a framework rewrite. Reliability, safety, compatibility and recovery are platform contracts; plugins remain the feature edge.

The active post-1.0 feature program is defined in **`ROADMAP.md`**. It is the working roadmap for Telegram Core 2.0, product/UX expansion, AI 2.0, durable automation, IntelGraph/IOC intelligence, media intelligence, cases, security intelligence, public-code intelligence and the plugin ecosystem.

## Core principles

1. Telegram remains the transport layer.
2. Plugins provide capabilities; shared services own infrastructure.
3. Command/plugin collisions are deterministic and observable.
4. Ephemeral tasks are supervised; restart-sensitive work is durable jobs.
5. SQLite is the default durable local store.
6. Cache and search state are derived and rebuildable.
7. AI providers are replaceable; AI output is never authority.
8. Side effects require authorization, bounded scope and verification where practical.
9. Secrets never enter source control, diagnostics or ordinary logs.
10. Resource use is bounded.
11. Isolation is claimed only where actually enforced.
12. The platform remains usable at ₹0/$0.

## Current platform

```text
Telegram / scheduler / owner command
                 │
                 ▼
          Command/Event Boundary
                 │
                 ▼
          ApplicationContext
                 │
      ┌──────────┼──────────┐
      ▼          ▼          ▼
   Plugins    JobEngine   Services
      │          │          │
      └──────────┼──────────┘
                 ▼
 Storage · Cache · HTTP · Subprocess · Telegram
 Media · AI · Search · Metrics · Flags · Isolation
```

Current production hardening includes deterministic plugin lifecycle and command ownership, bounded task/plugin/job shutdown, durable job leases/fencing/retry/`UNCERTAIN` handling, SQLite migration/checksum/integrity and verified backup/restore, bounded media workspaces, real Bubblewrap isolation for classified child workloads, FTS5 search, secret-safe diagnostics, provider-independent AI guardrails and behavioral/ecosystem audits.

## Plugin state

Current verified inventory:

- **41 active plugins**
- **4 intentionally quarantined legacy AI modules**

Quarantined:

```text
plugins.ai.ask
plugins.ai.groq_client
plugins.ai.summarize
plugins.ai.transcribe
```

Quarantine is intentional. Do not remove it merely because an AI command is unavailable.

## Documentation

| Document | Purpose |
|---|---|
| `ROADMAP.md` | Active Astra 2.x feature and implementation roadmap |
| `ARCHITECTURE.md` | Canonical architecture and production invariants |
| `DATA_MODEL.md` | Data ownership and persistence |
| `JOB_MODEL.md` | Durable job lifecycle and recovery semantics |
| `SAFETY_CONTRACT.md` | Mandatory safety rules |
| `PRODUCTION_BOUNDARY.md` | Authority and cross-boundary rules |
| `DECISIONS.md` | Accepted architecture decisions |
| `PLUGIN_SDK.md` | Plugin API contract |
| `PLUGIN_ECOSYSTEM.md` | Plugin lifecycle and metadata contract |
| `COMPATIBILITY.md` | Version and migration policy |
| `STORAGE_HARDENING.md` | Storage safety and integrity contract |
| `MEDIA_PIPELINE_HARDENING.md` | Media safety and resource contract |
| `ISOLATION_SECURITY.md` | Process-isolation contract |
| `OPERATIONS_RUNBOOK.md` | Day-to-day operator procedures |
| `UPGRADE_PROCEDURE.md` | Upgrade and rollback procedure |
| `DISASTER_RECOVERY.md` | Backup, restore and recovery procedure |
| `FAILURE_MODE_MATRIX.md` | Failure detection and response |
| `RELEASE_NOTES_v1.0.0.md` | v1.0.0 release summary |

Audit and verification implementations live under `tools/`; tests live under `tests/`. Historical phase/readiness and one-time release documents are intentionally not kept in the repository root.

## Verification

The canonical non-destructive verification gate is:

```bash
./venv/bin/python tools/production_acceptance_gate.py
```

Useful individual gates:

```bash
./venv/bin/python -m pytest -q
./venv/bin/python -m compileall -q core plugins tools
./venv/bin/python tools/plugin_behavior_audit.py
./venv/bin/python tools/plugin_ecosystem_audit.py
./venv/bin/python tools/media_pipeline_audit.py
./venv/bin/python tools/isolation_security_audit.py
./venv/bin/python tools/storage_hardening_audit.py
./venv/bin/python tools/job_hardening_audit.py
./venv/bin/python tools/phase18_production_audit.py
./venv/bin/python tools/phase18_shutdown_probe.py
```

The automated gate is non-destructive and does not restart the production system. Manual production checks are covered by the operator runbook.

## Operations

The operator-facing runtime views are:

```text
.health
.plugins
.tasks
.jobs
.cache
.stats
.diagnostics
.status
.ops
```

Production service lifecycle is managed by systemd. Follow `OPERATIONS_RUNBOOK.md` for normal operation and `FAILURE_MODE_MATRIX.md` for incident triage.

## Release model

`VERSION` contains the canonical release version. The current release is `1.0.0` and its Git tag is `v1.0.0`.

Release tags are immutable release markers; post-release maintenance commits remain on `main`.

## Zero-cost architecture

The core uses Python, Telethon, asyncio, SQLite/FTS5, aiohttp, Linux/FFmpeg tooling and optional genuinely-free/local AI providers. No paid API, hosted service or mandatory local LLM is required.

> **Power belongs at the plugin edge. Reliability belongs in the platform core.**
