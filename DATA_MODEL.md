# AstraUserbot — Detailed Data Model

**Status:** Mandatory data contract  
**Version:** 2.0  
**Scope:** Platform SQLite state, plugin metadata, commands, jobs, cache, media, audit, search, settings, migrations, retention

## 1. Purpose

Astra maintains local operational state while Telegram, external providers, the source repository, and user-controlled files remain authoritative for their own domains.

The central distinction is:

```text
AUTHORITATIVE EXTERNAL STATE
        ↓ observation
DERIVED LOCAL STATE
        ↓ orchestration
DURABLE ASTRA OPERATIONAL STATE
```

A local record must never silently become authoritative merely because it is persistent.

## 2. Authority Classes

### AUTHORITATIVE_EXTERNAL
Telegram state, external API state, source files, user-owned files, and other external systems.

### OBSERVED_DERIVED
Entity records, message indexes, HTTP responses, search indexes, OCR/transcripts, and similar observations.

### DURABLE_OPERATIONAL
Jobs, leases, migrations, audit records, plugin state, command registry metadata, health snapshots.

### CACHE
Disposable data governed by TTL/capacity/invalidation.

### CONFIGURATION
Non-secret user-controlled settings and policy.

### SECRET_REFERENCE
A pointer to secret material without embedding the secret itself.

## 3. Database Layout

Target shared platform database:

```text
~/.local/share/astra-userbot/astra.db
```

During migration, existing repository-local databases remain under `data/databases/`.

The platform database is introduced without destructive conversion. A plugin database moves only after:

1. schema is understood;
2. migration exists;
3. data backup exists;
4. consumer is migrated;
5. regression tests pass;
6. rollback is possible.

## 4. SQLite Baseline

Use:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = <bounded value>;
```

WAL is appropriate for concurrent readers/writers but does not remove the need for short transactions and bounded contention.

Transactions must contain local database work only. Do not hold a transaction while waiting on Telegram, HTTP, FFmpeg, AI, or another external system.

## 5. Canonical Tables

Initial platform schema:

```text
schema_migrations
plugins
plugin_dependencies
commands
command_aliases
jobs
job_attempts
job_events
leases
audit_events
cache_entries
entity_cache
message_cache
media_artifacts
settings
feature_flags
health_snapshots
search metadata / FTS tables
```

Tables may be split when scale or ownership requires it; the logical contracts remain stable.

## 6. Plugin Metadata

```text
plugin_id TEXT PRIMARY KEY
name TEXT NOT NULL
version TEXT NOT NULL
api_version TEXT NOT NULL
source_path TEXT NOT NULL
state TEXT NOT NULL
description TEXT
loaded_at INTEGER
failed_at INTEGER
error_code TEXT
error_summary TEXT
created_at INTEGER NOT NULL
updated_at INTEGER NOT NULL
```

Dependencies are separate rows so they can be queried and validated.

Constraints:

- plugin ID is stable;
- source path is unique for active registration;
- lifecycle state is an explicit enum;
- failure summaries are safe and bounded;
- metadata is not executable authority.

## 7. Command Model

Command definition:

```text
command_id TEXT PRIMARY KEY
plugin_id TEXT NOT NULL
canonical_name TEXT NOT NULL UNIQUE
description TEXT
permission TEXT NOT NULL
side_effect_class TEXT NOT NULL
state TEXT NOT NULL
registered_at INTEGER NOT NULL
updated_at INTEGER NOT NULL
```

Aliases:

```text
command_id TEXT NOT NULL
alias TEXT NOT NULL UNIQUE
```

A canonical command and any aliases share one handler/ownership definition. Duplicate aliases are conflicts.

## 8. Job Schema

Logical fields:

```text
job_id
job_type
priority
state
created_at
started_at
updated_at
completed_at
attempts
max_attempts
retry_at
payload_ref
scope_json
progress_json
error_code
error_message
worker_id
lease_until
heartbeat_at
parent_job_id
idempotency_key
verification_required
verification_state
```

Indexes should support:

```text
(state, retry_at, priority)
(worker_id, lease_until)
(parent_job_id)
(idempotency_key)
(created_at)
```

Job payloads contain intent and bounded references, never raw credentials or arbitrary executable Python.

## 9. Job Attempts

Each execution attempt may record:

```text
attempt_id
job_id
attempt_number
worker_id
started_at
finished_at
outcome
error_code
error_summary
external_effect_state
verification_state
```

This allows a job to distinguish current state from historical attempts.

## 10. Job Events

```text
event_id
job_id
event_type
timestamp
worker_id
state_before
state_after
summary
metadata_json
```

Event metadata is structured, bounded, and redacted.

## 11. Lease Model

A worker lease contains:

```text
job_id
worker_id
leased_at
lease_until
heartbeat_at
```

Only the current owner may renew/update a leased job. Expiry creates an uncertain/recovery state rather than success.

## 12. Audit Model

```text
audit_id
correlation_id
timestamp
actor
operation
plugin_id
command
job_id
scope
policy_result
authorization_result
verification_result
outcome
error_code
metadata_json
```

Audit records answer: **who/what/when/scope/result** without storing secrets.

## 13. Cache Schema

```text
namespace
key
version
created_at
expires_at
last_accessed_at
size_bytes
content_type
source
etag
last_modified
status
payload_ref
```

Primary key is `(namespace, key, version)` or an equivalent stable hash.

Cache entries require explicit expiration or invalidation semantics.

## 14. Entity Cache

Telegram entity observations may contain:

```text
entity_id
entity_type
username
title
access_hash
observed_at
expires_at
source
```

Sensitive identifiers are minimized. Cache membership never grants permission.

## 15. Message Cache

For deleted/edited reconstruction:

```text
message_id
chat_id
sender_id
received_at
edited_at
text_ref
media_ref
message_hash
expires_at
```

Capacity and retention are mandatory. A 500-entry volatile cache is not an acceptable universal persistence strategy for features that promise reconstruction beyond that window.

## 16. Media Artifacts

```text
artifact_id
job_id
kind
source_ref
path
mime_type
size_bytes
checksum
created_at
expires_at
status
```

Artifacts are derived unless explicitly promoted. Each job owns a workspace and artifact namespace.

## 17. Settings

Settings are typed conceptually as:

```text
configuration
policy
feature_flag
secret_reference
```

Secrets themselves are not normal settings values. Environment/configuration or the SecretStore provides secret material at runtime.

## 18. Health Snapshots

Operational snapshots may include:

```text
timestamp
process_uptime
telegram_state
plugin_summary
job_summary
cache_summary
db_summary
resource_summary
recent_error_count
```

Snapshots must be bounded and must not include secrets.

## 19. Search State

FTS/index tables are derived.

For example:

```text
messages_fts
notes_fts
documents_fts
plugins_fts
commands_fts
```

The authoritative record remains the source table/file. Search indexes must be rebuildable.

## 20. Migration System

Migration files are numbered and deterministic:

```text
0001_platform_base
0002_plugins_commands
0003_jobs
0004_cache
0005_audit
0006_media
0007_search
```

Migration runner rules:

1. open transaction where SQLite semantics allow;
2. check current version;
3. apply exactly next migration;
4. record checksum/version;
5. commit;
6. stop on failure;
7. never silently skip a migration.

Each migration has an upgrade test and, where feasible, rollback/recovery documentation.

## 21. Time Semantics

Persist UTC timestamps as a consistent representation. Keep concepts separate:

```text
created_at
observed_at
updated_at
started_at
completed_at
expires_at
retry_at
lease_until
```

`completed_at` means the job contract reached its terminal verified state, not merely that a subprocess exited 0.

## 22. Unknown and Nullable State

Unknown remains explicit:

```text
NULL
UNKNOWN
NOT_AVAILABLE
UNVERIFIED
```

Never invent checksums, provider metadata, timestamps, message IDs, MIME types, or verification results.

## 23. Referential Integrity

Foreign keys are enabled for platform relations. Deletion behavior is explicit.

Examples:

- deleting a plugin metadata row must not silently delete unrelated audit history;
- job children reference parents;
- command rows reference owners;
- artifacts reference jobs where applicable.

Audit/history tables use retention rather than accidental cascading deletion.

## 24. Retention

Every unbounded table or artifact class has a policy:

| Data | Required control |
|---|---|
| account archive | age/size retention |
| message cache | TTL + capacity |
| HTTP cache | TTL + byte cap |
| media artifacts | expiry + orphan cleanup |
| job history | age/count policy |
| audit | documented retention |
| logs | rotation + size |
| search indexes | rebuild/cleanup |

Retention must be resource-aware and observable.

## 25. Reconciliation

When derived state conflicts with external state:

```text
observe discrepancy
      ↓
classify
      ↓
invalidate/refresh
      ↓
reconcile side effects if needed
      ↓
audit material discrepancy
```

Never mutate Telegram or an external provider solely to make local cache state look consistent.

## 26. Backup and Restore

The platform database must have a tested backup/restore path before being treated as the sole home of durable state.

Backup must define:

- source database;
- consistency method;
- destination;
- retention;
- integrity check;
- restore procedure;
- verification result.

A backup command that merely copies a file is not automatically a verified backup system.

## 27. Security Rules

Never persist:

```text
Telegram session strings
API keys
bot tokens
passwords
private keys
raw authorization headers
cookies containing credentials
```

If a job needs a credential, store a provider/reference identifier and resolve the secret at execution time under authorization.

## 28. Plugin Database Migration

Existing databases are treated as independent bounded domains during transition. Migration sequence:

```text
inventory
→ schema capture
→ backup
→ repository adapter
→ shared-service migration
→ dual/read verification where useful
→ cutover
→ regression tests
→ old schema retirement
```

Do not force every plugin into the shared database merely for visual uniformity.

## 29. Data Integrity Invariants

1. External systems remain authoritative.
2. Derived records are refreshable.
3. Durable jobs are persisted.
4. Job attempts are distinguishable.
5. Verification is separate from execution.
6. Secrets are excluded.
7. Migrations are numbered.
8. Foreign keys protect platform relations.
9. Every unbounded store has retention.
10. Search indexes are rebuildable.
11. Media artifacts have ownership.
12. Cache loss cannot become source-data loss.
13. Unknown values remain explicit.
14. Audit data is structured and redacted.
15. Existing plugin data is migrated incrementally.

## 30. Implementation Acceptance Criteria

The data foundation is ready when tests prove:

- migrations create the expected schema;
- migrations are idempotent at the runner level;
- foreign-key violations are rejected;
- duplicate commands are rejected;
- job state is persisted across process recreation;
- leases expire predictably;
- cache entries expire;
- retention removes only eligible records;
- audit metadata is redacted;
- search indexes can be rebuilt;
- media artifacts can be orphan-cleaned;
- backup/restore preserves required platform state.

> **Astra stores what it must remember, derives what it can rebuild, and never mistakes persistence for authority.**
