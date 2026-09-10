# AstraUserbot — Architecture Decisions

**Status:** Living architectural record  
**Version:** 1.0  
**Scope:** Decisions constraining architecture, implementation, safety, compatibility, and evolution

This document prevents already-settled architecture from being reopened without new evidence. A later decision may supersede an earlier one only when it records what changed and why.

---

## ADR-001 — Keep a Single-Process Modular Monolith

**Status:** Accepted

### Decision
AstraUserbot remains one primary Python process with modular plugins and shared services.

### Rationale
The workload is asynchronous and local. Distributed infrastructure would add operational complexity without demonstrated need.

### Consequences
Redis, Kafka, RabbitMQ, Kubernetes, Celery, microservices, and remote queues are not default dependencies.

---

## ADR-002 — Telethon Remains the Telegram Transport

**Status:** Accepted

### Decision
Telethon remains the Telegram client/transport layer. Platform services may wrap common operations but raw Telethon remains available for advanced plugins.

### Consequences
The architecture must remain compatible with the current Telethon-based plugin ecosystem.

---

## ADR-003 — Build Shared Platform Services Before Mass Plugin Rewrites

**Status:** Accepted

### Decision
Do not rewrite all existing plugins first. Extract duplicated infrastructure into shared services, then migrate plugins incrementally.

### Rationale
The repository already contains substantial working behavior. The highest-value architectural work is removing duplicated infrastructure and improving lifecycle/observability.

### Consequences
Compatibility adapters are required during migration.

---

## ADR-004 — Central Plugin Lifecycle

**Status:** Accepted

### Decision
Plugin discovery, metadata, dependency handling, registration ownership, setup failure, shutdown, and health are controlled centrally.

### Consequences
A plugin failure must be visible in startup health instead of being mistaken for a fully healthy boot.

---

## ADR-005 — Central Command Router

**Status:** Accepted

### Decision
Commands and aliases are registered through one authoritative router with duplicate detection and plugin ownership.

### Rationale
The current plugin set contains duplicate `.block`/`.unblock` registrations. Direct independent registration permits ambiguous execution.

### Consequences
Duplicate command names/aliases become explicit conflicts.

---

## ADR-006 — Central Authorization and Capabilities

**Status:** Accepted

### Decision
Permissions and high-impact capabilities are represented centrally rather than implemented inconsistently in every plugin.

### Consequences
Existing self/outgoing command behavior can remain as compatibility behavior while explicit OWNER/ADMIN/TRUSTED/PUBLIC policy is introduced.

---

## ADR-007 — Durable Jobs for Restart-Sensitive Work

**Status:** Accepted

### Decision
Work that must survive process restart uses a SQLite-backed Job Engine.

### Rationale
Asyncio tasks are not durable.

### Consequences
Jobs use explicit state transitions, leases, retries, cancellation, verification, and recovery.

---

## ADR-008 — Task Supervisor for Long-Lived Ephemeral Tasks

**Status:** Accepted

### Decision
Long-lived process tasks use a central supervisor. TaskGroup is used for short-lived structured concurrency.

### Consequences
Every long-lived task has ownership, naming, exception handling, cancellation, and shutdown semantics.

---

## ADR-009 — SQLite as Default Local Persistence

**Status:** Accepted

### Decision
SQLite remains the default durable local database.

### Rationale
It is free, local, transactional, indexed, and operationally lightweight.

### Consequences
Use WAL where appropriate, foreign keys, busy timeouts, migrations, short transactions, and repository boundaries.

---

## ADR-010 — Tiered Cache

**Status:** Accepted

### Decision
Use bounded L1 memory, L2 SQLite, and L3 filesystem caching where workload justifies each tier.

### Consequences
Cache state remains disposable and versionable. No Redis dependency is required.

---

## ADR-011 — Shared HTTP Service

**Status:** Accepted

### Decision
Plugins should use a shared aiohttp session/service rather than creating independent clients.

### Consequences
Timeouts, pooling, concurrency, retries, response limits, and telemetry become consistent.

---

## ADR-012 — Shared Subprocess Service

**Status:** Accepted

### Decision
External commands use a centralized subprocess boundary.

### Consequences
Timeouts, cancellation, output limits, resource policies, and safe logging become common infrastructure.

---

## ADR-013 — MediaService for Media Workflows

**Status:** Accepted

### Decision
FFmpeg, downloads, speech, conversion, thumbnails, and temporary workspaces converge on a shared MediaService.

### Rationale
The current repository contains multiple duplicated media pipelines and inconsistent cleanup/output selection.

### Consequences
Every media job receives a unique workspace and deterministic output path.

---

## ADR-014 — Provider-Independent AI Gateway

**Status:** Accepted

### Decision
AI integrations use a provider-independent gateway with local models first and optional free hosted adapters.

### Rationale
Provider APIs/models change. Core behavior must not be coupled to one vendor.

### Consequences
Groq becomes an adapter rather than the AI architecture. Ollama/local inference can operate without network credentials.

---

## ADR-015 — AI Is Advisory

**Status:** Accepted

### Decision
AI output is untrusted input and never final authority for consequential mutations.

### Consequences
Deterministic validation and authorization remain mandatory.

---

## ADR-016 — Verification Before Completion

**Status:** Accepted

### Decision
Operations requiring verification are not complete until their postconditions are verified.

### Consequences
A successful subprocess/API response cannot alone produce a completed durable job.

---

## ADR-017 — Explicit Failure Classification

**Status:** Accepted

### Decision
Retry decisions use stable failure classes/codes rather than arbitrary exception-string parsing.

### Initial classes

```text
TRANSIENT
RATE_LIMITED
PERMANENT
INTEGRITY
RESOURCE_LIMIT
CANCELLED
INTERNAL
```

---

## ADR-018 — Proper Cryptography Only

**Status:** Accepted

### Decision
Base64 or encoding is never described as encryption. Secret storage uses reviewed authenticated encryption and appropriate key derivation.

### Rationale
The existing repository contains two vault concepts with materially different security properties; they must converge on one proper SecretStore.

---

## ADR-019 — Resource Awareness Is Architectural

**Status:** Accepted

### Decision
CPU, RAM, disk, network, Telegram limits, and cache growth are explicit scheduling constraints.

### Consequences
Bounded concurrency and backpressure are preferred over maximum throughput.

---

## ADR-020 — No Mandatory Paid Infrastructure

**Status:** Accepted

### Decision
AstraUserbot remains usable at ₹0 / $0.

### Consequences
Local/open-source components and existing host capabilities are preferred. Free hosted APIs may be optional adapters but never mandatory foundations.

---

## ADR-021 — Preserve Existing Plugin Behavior During Migration

**Status:** Accepted

### Decision
Migration should preserve behavior unless a defect is identified and deliberately fixed.

### Consequences
Compatibility tests are required for high-value plugins and workflows.

---

## ADR-022 — Fix Confirmed P0 Defects Before Expansion

**Status:** Accepted

### Initial confirmed defects

1. Duplicate `.block`/`.unblock` registration between ACL and PM guard.
2. Admin commands advertised but not actually implemented (`demote`, `slow`).
3. Security vault using base64 obfuscation instead of encryption.
4. Concurrent eval manipulating global `sys.stdout`.
5. Silent failure around account archival persistence.

### Consequences
Feature expansion does not outrank correctness of existing high-impact paths.

---

## ADR-023 — Centralize Retention

**Status:** Accepted

### Decision
Every unbounded data source requires an explicit retention/capacity policy.

### Applies to

- account archives;
- message reconstruction cache;
- logs;
- audit events;
- media artifacts;
- HTTP cache;
- job history.

---

## ADR-024 — Avoid Heavy Frameworks Until Proven Necessary

**Status:** Accepted

### Decision
Do not adopt large generic frameworks merely for architectural appearance.

### Explicitly not default

```text
Redis
Kafka
RabbitMQ
Celery
Kubernetes
microservices
ORM-heavy persistence
LangChain/LlamaIndex as core
LiteLLM as mandatory gateway
Prometheus/Grafana as mandatory stack
OpenTelemetry as mandatory stack
APScheduler as a prerequisite
automatic hot reload
```

Each may be reconsidered only with concrete evidence.

---

## ADR-025 — Architecture Changes Require Evidence

**Status:** Accepted

A decision may be revisited because of:

- demonstrated implementation failure;
- new hard requirement;
- measured performance bottleneck;
- security finding;
- major dependency change;
- production workload change.

Preference alone is insufficient to overturn a safety invariant.

## Decision Review Rule

When superseding an ADR, record:

- old decision;
- new decision;
- evidence;
- affected components;
- migration plan;
- compatibility impact;
- safety impact.

> **Change architecture deliberately, record why, preserve compatibility, and never let implementation convenience silently change the system's authority model.**
