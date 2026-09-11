# AstraUserbot

AstraUserbot is a modular Telegram userbot platform being hardened into a service-oriented, durable, local-first automation system.

The project is intentionally a **single-process modular monolith**. Telethon remains the Telegram transport; shared platform services own persistence, jobs, cache, HTTP, subprocesses, workspaces, secrets, and lifecycle.

## Current architecture posture

```text
Telegram / external systems
          |
      Telethon
          |
   Command / Event Router
          |
   Authorization + Plugins
          |
   ApplicationContext
          |
  +-------+--------+---------+---------+
  |       |        |         |         |
Storage Cache    Jobs    Subprocess  HTTP
  |                 |                  |
 SQLite         durable work      shared network
  |
 SecretStore / Workspace / TelegramFacade
```

The architecture deliberately avoids Redis, Kafka, Celery, Kubernetes, microservices, ORM-heavy persistence, and other infrastructure that would add cost or operational weight without improving this project's current failure model.

## 1. Engineering invariants

- The model/provider is never the authority for side effects.
- Every mutating operation has an explicit authorization boundary.
- Durable work survives an AI/session/process restart.
- Plugin failure must not crash the platform.
- Shared services own cross-cutting infrastructure.
- Persistent stores have explicit retention or bounded capacity.
- Secrets are never treated as base64-obfuscated plaintext.
- External subprocesses use argv execution, bounded output, cancellation and timeouts.
- HTTP traffic uses the shared bounded service where migrated.
- Temporary media/work files have deterministic cleanup.
- Existing plugin behavior is preserved during migration unless a documented reliability defect requires change.

## 2. Current Development Stage

**Phase 1 — Plugin & Command Foundation: COMPLETE.**

- Plugin Manager;
- Command Router;
- Safe Errors;
- TaskSupervisor;
- lifecycle ownership and collision regression coverage.

**Phase 2 — Shared Runtime Services: COMPLETE.**

- ApplicationContext with explicit service ownership/lifecycle;
- bounded/cancellable SubprocessService;
- shared pooled HttpService;
- TelegramFacade;
- WorkspaceService with safe paths, per-operation workspaces, size limits and orphan cleanup;
- legacy shell/network compatibility routed through shared services.

**Phase 3 — Cache Foundation: COMPLETE.**

- bounded L1/L2/L3 cache tiers;
- TTL, namespaces, versioning and invalidation;
- artifact metadata and atomic writes;
- stampede protection and diagnostics.

**Phase 4 — Storage & Migration Foundation: COMPLETE.**

- canonical platform SQLite database;
- deterministic migration runner with schema versions and checksums;
- WAL, foreign keys, busy timeout and integrity checks;
- transactional migration execution;
- platform tables for plugins, commands, jobs, attempts, events, leases and audit records;
- verified SQLite backup/restore support;
- ApplicationContext integration through `StorageService`.

**Phase 5 — Durable Job Engine: COMPLETE.**

- durable job persistence;
- canonical job states;
- worker leasing and heartbeat;
- expired-lease recovery;
- bounded retry/backoff and stable failure codes;
- idempotency and cancellation;
- progress, verification, attempts and event history;
- handler registration and supervised worker loop;
- ApplicationContext lifecycle integration.

**Phase 6 — Confirmed P0 Reliability Fixes: IMPLEMENTED; gate pending local verification.**

- `.block` / `.unblock` now have one command owner;
- advertised admin `demote` and `slow` commands are implemented;
- security vault now uses AES-256-GCM SecretStore with external master key and legacy base64 migration;
- eval output capture is serialized, isolated from module globals, bounded, and timeout-controlled;
- account archiver now surfaces persistence failures and has age/count retention plus orphan pruning;
- logger has bounded L1 plus persistent bounded/retained message cache;
- PMGuard refreshes contacts periodically instead of caching only at startup;
- AFK auto-replies have a bounded per-sender cooldown;
- stream downloads use unique workspaces and deterministic cleanup;
- media temporary files clean up on failure paths;
- rclone/aria2 use the shared SubprocessService when the runtime context is available;
- Phase 6 regression coverage added for command ownership, admin surface, secrets, eval concurrency, retention, cooldowns, media isolation and subprocess routing.

**Gate 6:** run the full test and compile gate locally. No bot restart is required for test-only verification.

## 3. Definition of Success

Astra succeeds when adding the next 100 useful features does not require inventing another HTTP client, scheduler, cache, temp-file strategy, subprocess wrapper, database pattern, or authorization mechanism.

> **Power belongs at the plugin edge. Reliability belongs in the platform core.**
