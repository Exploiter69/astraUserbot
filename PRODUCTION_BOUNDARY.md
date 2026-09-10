# AstraUserbot — Production & Runtime Boundary

**Status:** Mandatory Architectural Contract  
**Scope:** Telegram account, local runtime, repository, external services, and Astra automation

## 1. Purpose

AstraUserbot is a powerful automation process. It can interact with Telegram, the local filesystem, subprocesses, databases, and external APIs. This document defines what the platform owns, what it merely observes, and what requires explicit authorization.

## 2. Ownership Model

```text
Telegram
  → authoritative Telegram state

External providers
  → authoritative provider state

Local source repository
  → authoritative source code

Astra runtime state
  → Astra-owned operational state

Caches / indexes
  → derived, disposable state
```

Astra must never confuse a local cache or index with authority over an external system.

## 3. Repository Boundary

The Git repository contains source, tests, documentation, migrations, and safe configuration templates.

It must not contain:

- Telegram session files;
- session strings;
- API keys;
- bot tokens;
- passwords;
- production database dumps;
- private provider credentials;
- generated media/cache artifacts;
- runtime logs unless deliberately sanitized fixtures.

`.gitignore` and pre-commit/pre-push checks should enforce this boundary.

## 4. Runtime Boundary

Runtime data may include:

```text
data/
~/.local/share/astra-userbot/
~/.cache/astra-userbot/
```

The exact location may evolve, but source control and runtime state must remain separate.

Temporary media/download artifacts belong in dedicated temporary workspaces and must be cleaned after completion or failure.

## 5. Telegram Boundary

Telegram is an external authoritative system.

Astra may perform actions permitted by the authenticated account and the command's authorization policy, but must not treat local state as proof that Telegram state still exists.

Actions with broad account impact require explicit command scope and appropriate authorization.

## 6. Protected Session State

Telegram authentication/session state is protected.

The platform must not:

- print it;
- commit it;
- include it in diagnostics;
- send it to AI providers;
- expose it through command output;
- silently rotate/invalidate it;
- copy it into unrelated caches.

## 7. Local Filesystem Boundary

Filesystem capabilities are divided into:

```text
READ_ALLOWED_ROOTS
WRITE_ALLOWED_ROOTS
TEMP_ROOTS
PROTECTED_ROOTS
```

The platform must canonicalize paths and reject traversal or ambiguous paths.

A plugin must not assume that a path supplied by a user is safe merely because it looks relative or begins with an expected string.

## 8. Subprocess Boundary

External programs are outside Python's direct control and must be treated as privileged capabilities.

All subprocess execution should eventually pass through the shared SubprocessService.

Protected behavior includes:

- no unsafe shell interpolation;
- timeouts;
- cancellation;
- output limits;
- executable validation where practical;
- explicit working directories;
- resource limits;
- safe logs.

## 9. Network Boundary

HTTP integrations are external systems.

The shared HTTP service should control:

- allowed schemes;
- timeouts;
- redirects;
- response sizes;
- concurrency;
- retries;
- authentication header redaction.

A plugin accepting an arbitrary URL must not silently gain unlimited download or internal-network access.

## 10. Database Boundary

Astra's SQLite state is operational state owned by Astra.

External databases, if accessed, remain external authorities.

A plugin must not:

- silently drop another plugin's database;
- change a shared schema without migration;
- run long network operations inside a transaction;
- treat stale local records as external truth.

## 11. Plugin Boundary

Plugins are modules inside one process, not separate trust domains.

Therefore the Plugin Manager provides lifecycle and ownership controls but does not pretend to provide process isolation.

A plugin may declare capabilities, but the platform must enforce high-impact capabilities centrally where practical.

## 12. Command Boundary

Every registered command has:

- owner plugin;
- canonical name;
- aliases;
- description;
- permission requirement;
- side-effect classification.

Duplicate names/aliases are rejected.

No plugin may silently replace another plugin's command.

## 13. Background Work Boundary

Ephemeral background tasks are process-local.

Durable work belongs to the Job Engine.

A feature may not claim restart survival unless its intent and lifecycle are persisted.

## 14. External Side Effects

Examples of external side effects include:

- sending/editing/deleting Telegram messages;
- modifying chat permissions;
- joining/leaving chats;
- changing local files;
- executing programs;
- calling APIs with mutation semantics;
- publishing content;
- sending notifications;
- changing account state.

These actions require explicit policy and authorization appropriate to their impact.

## 15. Destructive Boundary

High-impact/destructive actions include:

- mass message deletion;
- mass editing;
- permission changes;
- account configuration changes;
- filesystem deletion/overwrite;
- bulk external writes;
- irreversible media transformations over originals.

Such operations require a deterministic target set, authorization, bounded execution, and verification/audit where practical.

## 16. AI Boundary

AI has no independent authority over any protected boundary.

AI may propose:

```text
classification
search interpretation
summaries
tags
plans
commands
```

The deterministic platform must validate any proposal before execution.

AI must never receive secrets merely because a plugin has access to them.

## 17. Cache Boundary

Caches are disposable.

A cache may be deleted, rebuilt, expired, or invalidated without changing authoritative external state.

Cache refresh must not perform hidden destructive actions.

## 18. Media Boundary

Media downloads and generated files are temporary unless explicitly promoted.

Every job owns its workspace.

A failed job must not leave an unbounded accumulation of files.

Original source files are not overwritten by default.

## 19. Account Automation Boundary

Automatic replies, scheduled messages, posting, cleanup, and other account automation must have bounded concurrency, rate awareness, and clear ownership.

Per-user/per-chat cooldowns should be used where repeated automated responses could create unnecessary traffic.

## 20. Monitoring Boundary

Monitoring is observational by default.

A health check may report:

- Telegram connectivity;
- plugin health;
- database health;
- cache state;
- job state;
- resource pressure;
- external API health.

It does not gain automatic repair authority merely by being a monitor.

## 21. Failure Boundary

When ownership or scope is uncertain:

```text
uncertain target     → stop
uncertain permission → stop
uncertain credential → stop
uncertain side effect → stop
uncertain completion → verify/reconcile
```

The system must not convert uncertainty into increasingly invasive automation.

## 22. Boundary Tests

Permanent tests should prove:

1. secrets cannot be loaded from committed fixtures accidentally;
2. protected runtime paths are recognized;
3. path traversal is rejected;
4. unauthorized commands are rejected;
5. duplicate command registration fails;
6. subprocess timeouts work;
7. HTTP response limits work;
8. AI proposals cannot bypass policy;
9. durable jobs survive restart;
10. cache deletion cannot delete authoritative data;
11. media workspaces are isolated;
12. monitoring has no hidden mutation;
13. destructive operations require explicit authorization.

## Operational Rule

> **Astra owns its orchestration and operational state. Telegram, external providers, and source data remain their own authorities. Boundaries must be explicit, testable, and enforced centrally.**
