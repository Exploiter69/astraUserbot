# AstraUserbot — Detailed Production & Runtime Boundary

**Status:** Mandatory architectural contract  
**Version:** 2.0  
**Scope:** Repository, runtime, Telegram, filesystem, processes, network, database, plugins, jobs, media, AI, external services

## 1. Purpose

Astra is a privileged local process connected to a Telegram account. This document defines what each boundary owns, what Astra observes, and where explicit authorization is required.

## 2. Authority Model

```text
Telegram                → authoritative Telegram state
External provider      → authoritative provider state
Source repository      → authoritative source code
User-controlled files  → authoritative file content
Astra database         → Astra operational state
Caches/indexes         → derived disposable state
```

No local cache or database record overrides an external authority.

## 3. Repository Boundary

The Git repository contains source, tests, migrations, documentation, fixtures, and safe configuration templates.

Never commit:

```text
.env
Telegram session files/strings
API keys
bot tokens
passwords
private keys
production DB dumps
runtime logs containing secrets
cache/media artifacts
```

`.gitignore` and repository checks must enforce the boundary.

## 4. Runtime Boundary

Runtime state is separate from source:

```text
~/AstraUserbot/data/
~/.local/share/astra-userbot/
~/.cache/astra-userbot/
```

Exact paths may evolve, but the ownership distinction remains.

## 5. Telegram Boundary

Telegram is authoritative for:

- chats;
- messages;
- participants/permissions;
- account state;
- Telegram media references;
- server-side scheduling/limits.

Astra's cached observations may be stale. Before high-impact mutations, resolve current state where practical.

## 6. Session Boundary

The Telegram session is protected credential state.

It must never be:

- printed;
- committed;
- sent to AI;
- included in diagnostics;
- copied into cache;
- placed into job payloads;
- exposed through error messages.

## 7. Filesystem Boundary

Filesystem policy distinguishes:

```text
SOURCE_ROOT
DATA_ROOT
CACHE_ROOT
TEMP_ROOT
EXPORT_ROOT
PROTECTED_ROOTS
```

Every path crossing a plugin/service boundary is validated and canonicalized. Symlink and traversal behavior must be considered where protected roots are involved.

## 8. Subprocess Boundary

External binaries are privileged capabilities. They execute outside Python's memory safety model and can have broad filesystem/network access.

All platform-managed subprocesses should pass through SubprocessService with:

- argv execution;
- timeout;
- cancellation;
- output caps;
- cwd policy;
- environment policy;
- resource policy;
- result classification.

## 9. Network Boundary

HTTP/API integrations use the shared HTTP service.

Policy covers:

```text
scheme
host/target rules
redirects
timeouts
response size
concurrency
retries
credentials/logging
```

Arbitrary URL features require deliberate policy and bounded downloads.

## 10. Database Boundary

Astra SQLite databases are operational stores.

Rules:

- migrations for shared schema changes;
- foreign keys enabled;
- short transactions;
- bounded queries;
- no external network call inside transactions;
- explicit ownership of plugin data;
- retention for unbounded history.

## 11. Plugin Boundary

Plugins are code in the same Python process. They are modular but not security-isolated.

The Plugin Manager controls lifecycle and registration ownership but cannot prevent a malicious/buggy plugin from accessing process memory. Strong isolation requires a separate process/container and is intentionally deferred.

## 12. Command Boundary

Each command has:

```text
canonical name
aliases
owner plugin
permission
capabilities
side-effect class
scope
```

Duplicate commands are rejected. Plugins cannot silently override existing registrations.

## 13. Event Boundary

Telethon events are transport events. Plugins may subscribe through the platform, but handlers must be tracked so they can be disabled/unloaded cleanly.

A tiny internal event bus may be used for genuine application events. It must not become a hidden second Telegram transport.

## 14. Background Work Boundary

Process-local tasks are ephemeral. Durable jobs are persisted.

```text
watcher/poller/cleanup → TaskSupervisor
restart-sensitive work → Job Engine
```

A feature may not claim restart survival without persisted intent and lifecycle.

## 15. External Side-Effect Boundary

Examples:

```text
Telegram send/edit/delete
Telegram permission changes
chat membership changes
filesystem writes/deletes
subprocess execution
external API mutations
posting/publishing
credential/account changes
```

These actions require explicit capability and scope.

## 16. Destructive Boundary

Destructive/high-impact operations include mass deletion, overwrite, purge, revoke, promotion/demotion, account changes, bulk external writes, and irreversible transformations.

Required controls:

1. deterministic target set;
2. authorization;
3. bounded execution;
4. rate limits;
5. verification where possible;
6. audit trail;
7. preview/dry-run where practical.

## 17. Job Boundary

Jobs cannot broaden their own scope after creation. A worker executes the persisted contract.

Changing a job from read to write, narrow to broad, or reversible to destructive requires a new policy/authorization decision.

## 18. Cache Boundary

Cache data is derived and disposable.

Deleting cache must not delete authoritative source data. Cache refresh must not contain hidden destructive behavior.

## 19. Media Boundary

Media artifacts are temporary by default.

Every job receives an isolated workspace. Originals are preserved unless explicit overwrite behavior is authorized.

A failed job must not leak unlimited disk usage.

## 20. AI Boundary

AI has no independent authority over protected boundaries.

```text
Natural language
      ↓
AI interpretation
      ↓
typed proposal
      ↓
deterministic validation
      ↓
authorization
      ↓
execution
```

AI never receives secrets merely because the runtime has them.

## 21. Account Automation Boundary

AFK, autopost, scheduled messages, bulk actions, cleanup, and similar automation require:

- explicit scope;
- bounded concurrency;
- Telegram rate awareness;
- cooldowns where needed;
- durable scheduling when restart survival is promised.

## 22. Monitoring Boundary

Monitoring is read-only by default.

Health checks may inspect Telegram, plugins, tasks, jobs, DB, cache, resources, and external APIs. They do not gain automatic repair authority.

## 23. Observability Boundary

Logs and diagnostics may cross internal boundaries only after redaction.

Allowed diagnostic metadata includes IDs, timings, state, counts, and classified errors. Secrets and raw sensitive payloads are forbidden.

## 24. Failure Boundary

```text
unknown target       → stop
unknown permission   → stop
unknown credential   → stop
unknown scope        → stop
unknown completion   → reconcile/verify
resource exhaustion  → backpressure
```

## 25. Recovery Boundary

Recovery must not silently expand impact.

A crashed worker may recover only within its original job scope. Uncertain external effects require reconciliation before replay where practical.

## 26. Production Configuration Boundary

Production configuration must be explicit:

```text
Telegram credentials
runtime roots
resource limits
plugin enable/disable policy
network policy
job worker limits
cache limits
AI provider configuration
logging/retention
```

Defaults must be conservative and local-first.

## 27. Backup Boundary

Backups are copies of Astra-owned state. A backup destination is external state and must be treated as such.

A backup operation is successful only after the configured artifact can be verified according to its backup contract.

## 28. Boundary Tests

Tests must prove:

- secret exclusion;
- protected path handling;
- traversal rejection;
- command ownership/conflict handling;
- permission enforcement;
- subprocess timeout/cancel/output limits;
- HTTP limits;
- AI cannot bypass policy;
- jobs survive restart;
- media workspaces isolate concurrent jobs;
- cache deletion does not delete source data;
- monitoring has no hidden mutation.

## 29. Boundary Ownership Table

| Boundary | Authority | Astra role |
|---|---|---|
| Telegram | Telegram | client/orchestrator |
| External API | Provider | integration |
| Source code | Git repository | developer-controlled |
| User files | Filesystem/user | controlled accessor |
| Jobs | Astra DB | durable owner |
| Cache | Astra | disposable derived state |
| Search index | Astra | rebuildable derived state |
| Plugins | Astra runtime | lifecycle owner |
| Secrets | runtime secret source | controlled consumer |

## Final Operational Rule

> **Astra owns orchestration and operational state. Every other boundary keeps its authority. Cross-boundary actions are explicit, scoped, testable, and observable.**
