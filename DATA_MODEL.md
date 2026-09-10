# AstraUserbot — Data Model

**Status:** Mandatory architectural contract  
**Scope:** Userbot runtime state, plugin metadata, jobs, cache, audit, security metadata, and derived search state

## 1. Purpose

AstraUserbot already contains multiple plugin-specific SQLite databases. The platform needs a canonical data model for durable infrastructure without forcing an immediate destructive migration of working plugins.

The model distinguishes authoritative external state from Astra's observations and operational state.

```text
Telegram / external systems / filesystem
            ↓
       observed state
            ↓
      Astra local state
            ↓
 jobs / cache / search / audit / diagnostics
```

Astra's local databases are not authoritative for Telegram content or external provider state.

## 2. Runtime Locations

Repository source remains separate from runtime state.

Recommended runtime layout:

```text
~/AstraUserbot/
  source code + migrations + tests

~/AstraUserbot/data/
  existing plugin/runtime data during migration

~/.local/share/astra-userbot/
  future consolidated platform database and durable state

~/.cache/astra-userbot/
  disposable cache, media, downloads, thumbnails, temporary artifacts
```

Existing working plugin databases must remain intact until each consumer is migrated and verified.

## 3. Authority Classes

Every persistent record should conceptually belong to one of these classes:

### AUTHORITATIVE_EXTERNAL

Facts owned by Telegram, an external API, the filesystem, or another external system.

### OBSERVED_DERIVED

Astra's cached/indexed observation of external state. It can become stale and must be refreshable.

### DURABLE_OPERATIONAL

Astra-owned state required to survive restarts, such as jobs, leases, retry schedules, migrations, and audit events.

### CACHE

Disposable derived data with an expiry or invalidation policy.

### CONFIGURATION

User-controlled policy and non-secret configuration.

The distinction must never be lost merely because records live in the same SQLite database.

## 4. Platform Database

The long-term platform database should be SQLite with WAL where appropriate.

Conceptual tables include:

```text
schema_migrations
plugins
plugin_dependencies
commands
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
```

Individual plugin databases may continue to exist until migration is justified.

## 5. Plugin Record

Canonical fields:

| Field | Meaning |
|---|---|
| `plugin_id` | Stable internal identifier |
| `name` | Human-readable plugin name |
| `version` | Plugin version |
| `api_version` | Supported plugin API |
| `state` | Lifecycle state |
| `source_path` | Repository module path |
| `description` | Human-readable purpose |
| `dependencies` | Required plugin IDs |
| `optional_dependencies` | Optional plugin IDs |
| `permissions` | Declared capabilities |
| `loaded_at` | Last successful load time |
| `failed_at` | Last failure time |
| `error_code` | Classified failure |
| `error_summary` | Safe diagnostic summary |

Plugin records are operational metadata, not executable authority.

## 6. Command Record

Canonical fields:

| Field | Meaning |
|---|---|
| `command_id` | Stable command registration ID |
| `name` | Canonical command name |
| `plugin_id` | Owning plugin |
| `aliases` | Registered aliases |
| `description` | Help text |
| `permission` | Required authorization level/capability |
| `state` | Active/disabled/conflicted |
| `registered_at` | Registration time |

Command identity must be unique across the active plugin set. Duplicate aliases are conflicts, not two normal handlers.

## 7. Job Record

The Job Model is authoritative for durable work.

Required logical fields:

```text
job_id
type
priority
state
created_at
started_at
updated_at
completed_at
attempts
max_attempts
retry_at
source
destination
scope
progress
error_code
error_message
worker_id
lease_until
parent_job_id
idempotency_key
verification_required
verification_state
```

Secrets, raw credentials, session strings, authorization headers, and private tokens are forbidden in job payloads.

## 8. Job Event Record

Each material lifecycle transition can have an event:

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

Metadata is structured and redacted. It must not become an uncontrolled dump of command output.

## 9. Audit Record

Audit records explain meaningful actions:

```text
audit_id
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
correlation_id
```

Secrets are never stored in audit metadata.

## 10. Cache Record

Persistent cache entries should contain:

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
payload_reference
```

Large binary content should normally live in the filesystem cache and be referenced by metadata.

Cache state is disposable. Cache corruption must never corrupt authoritative external state.

## 11. Entity Cache

Frequently resolved Telegram entities can be cached with fields such as:

```text
entity_id
entity_type
username
phone_hash_or_redacted_identifier
title
access_hash_when_required
observed_at
expires_at
source
```

Sensitive identifiers should not be logged unnecessarily. Entity cache entries are observations, not permission grants.

## 12. Message Cache

Features such as deleted/edited message reconstruction require bounded message state.

Logical fields:

```text
message_id
chat_id
sender_id
received_at
edited_at
text_reference
media_reference
message_hash
expires_at
source
```

The cache must have explicit capacity/retention. A fixed in-memory cache alone is not a durable message history.

## 13. Media Artifact

Media processing produces derived artifacts:

```text
artifact_id
job_id
source_reference
path
mime_type
size_bytes
checksum
created_at
expires_at
kind
status
```

Artifacts are disposable unless explicitly promoted into a user-controlled location.

Each media job gets an isolated workspace to prevent concurrent output collisions.

## 14. Settings

Settings should distinguish:

- ordinary configuration;
- feature toggles;
- policy;
- secret references.

Secrets themselves remain outside normal settings records where possible and are loaded from environment/secure local configuration.

## 15. Migration Model

Schema migrations are numbered and deterministic:

```text
0001_initial_platform
0002_jobs
0003_cache
0004_audit
...
```

Every migration has tests and documents compatibility assumptions.

Plugin-specific schemas remain versioned independently until migrated.

## 16. Time Semantics

All persisted timestamps use timezone-safe UTC representation.

Different concepts must not be conflated:

```text
created_at       = object/record creation
observed_at      = external observation
updated_at       = local record update
expires_at       = cache validity
started_at       = execution start
completed_at     = verified terminal completion
```

## 17. Unknown Values

Unknown remains unknown.

Do not fabricate:

- timestamps;
- MIME types;
- Telegram identifiers;
- checksums;
- provider metadata;
- verification results.

Use `NULL`, explicit unknown states, or equivalent typed representations.

## 18. Search State

Search indexes are derived state.

The initial search stack should use SQLite indexes and FTS5 where justified.

Potential indexed data:

- command metadata;
- plugin metadata;
- cached message text;
- notes;
- document text;
- OCR output;
- transcripts.

Search indexes can be rebuilt and must never be treated as the authoritative source of the underlying content.

## 19. Security Metadata

Security-sensitive state should include enough information for audit without storing secrets.

Examples:

```text
permission checks
command ownership
authorization decisions
rate-limit observations
security events
credential-provider names
```

Do not persist raw session strings, API hashes, tokens, passwords, private keys, or cookies.

## 20. Referential Integrity

Where relational relationships exist, use foreign keys and explicit deletion behavior.

A plugin cannot silently delete platform records belonging to another plugin.

Job history and audit history should be retained according to documented retention policy rather than opportunistic deletion.

## 21. Reconciliation

External observations can become stale.

When a cache/index conflicts with Telegram or another authoritative source:

1. record the discrepancy;
2. invalidate or refresh derived state;
3. preserve audit evidence when material;
4. never mutate the authoritative source merely to make local state match.

## 22. Data Retention

Every unbounded data source requires retention policy.

This applies especially to:

- account archiver data;
- message reconstruction caches;
- logs;
- audit records;
- media artifacts;
- HTTP response caches;
- job history.

Retention must be configurable and resource-aware.

## 23. Integrity Invariants

1. Telegram/external systems remain authoritative for external state.
2. Local indexes and caches are derived.
3. Durable jobs are platform-owned operational state.
4. Unknown data remains unknown.
5. Secrets never enter normal persistent records.
6. Schema changes are versioned.
7. Cache loss cannot become data loss.
8. Job state cannot be reconstructed from volatile memory alone.
9. Audit data is structured and redacted.
10. Existing plugin databases are migrated incrementally.
11. Search state is rebuildable.
12. Retention exists for every unbounded data source.
13. Media artifacts have explicit ownership and cleanup semantics.
14. Verification state is distinct from execution state.
15. Derived state must never silently gain authority over the external system.

## 24. Minimum Initial Implementation

The platform data foundation should begin with:

- migration table;
- plugin registry metadata;
- command registry metadata;
- durable jobs;
- job events;
- audit events;
- persistent cache metadata;
- health/runtime snapshots;
- repositories and tests.

Do not block the platform on a complete migration of all existing plugin databases.

## Operational Principle

> **Astra's database records what Astra must remember; it does not become the authority for what Telegram, the filesystem, or an external provider actually contains.**
