# AstraUserbot — Job Model

**Status:** Architecture Contract  
**Scope:** Durable asynchronous execution inside AstraUserbot  
**Authority:** AstraUserbot runtime for operational state; Telegram and external systems remain authoritative for their own state

## 1. Purpose

A background asyncio task disappears when the process disappears. A durable job does not. Astra needs a persistent execution model for reminders, scheduled actions, retryable API work, media processing, indexing, backups, maintenance, and other operations that may outlive a command invocation.

The central invariant is:

> **Accepted durable work must remain explainable and recoverable across process restart, network loss, cancellation, and worker failure.**

A job is not complete merely because an executor returned successfully. Where verification is required, completion follows verification.

## 2. Job Position

```text
Command / Event / Scheduler
          ↓
       Validate
          ↓
      Authorize
          ↓
        Plan
          ↓
    Durable Job Queue
          ↓
        Worker
          ↓
     External action
          ↓
      Verification
          ↓
        Audit
```

The Job Engine does not grant permissions. It executes only a bounded, already-authorized operation.

## 3. Canonical Job Types

Initial types:

```text
REMINDER
SCHEDULED_MESSAGE
HTTP_TASK
MEDIA_PROCESS
DOWNLOAD
UPLOAD
INDEX
BACKUP
MAINTENANCE
SYNC
AI_TASK
PLUGIN_TASK
```

New high-impact job types require a recorded architectural decision.

## 4. Job Identity

Every job has:

- globally unique `job_id`;
- creation timestamp;
- canonical job type;
- bounded payload/reference;
- optional `idempotency_key`;
- parent job when part of a workflow.

The payload must describe intent, not contain secrets or arbitrary executable code.

## 5. Canonical Fields

| Field | Meaning |
|---|---|
| `job_id` | Stable unique identifier |
| `type` | Canonical job type |
| `priority` | Scheduling priority |
| `state` | Current lifecycle state |
| `created_at` | Creation time |
| `started_at` | Latest execution start |
| `updated_at` | Last state/progress update |
| `completed_at` | Terminal completion time |
| `attempts` | Attempts consumed |
| `max_attempts` | Retry ceiling |
| `retry_at` | Earliest next attempt |
| `payload_ref` | Bounded operation payload/reference |
| `progress` | Informational progress |
| `error_code` | Stable failure class/code |
| `error_message` | Safe diagnostic summary |
| `worker_id` | Current lease owner |
| `lease_until` | Lease expiry |
| `parent_job_id` | Optional workflow parent |
| `idempotency_key` | External-side-effect deduplication key |
| `verification_required` | Whether postcondition verification is mandatory |
| `verification_state` | Verification lifecycle |

No raw credentials, session strings, authorization headers, cookies, private keys, or passwords are stored.

## 6. States

```text
QUEUED
RUNNING
PAUSED
VERIFYING
COMPLETED
FAILED
CANCELLED
```

Normal path:

`QUEUED → RUNNING → VERIFYING → COMPLETED`

Read-only jobs may transition directly from `RUNNING` to `COMPLETED` when their contract has no separate verification requirement.

## 7. State Transition Rules

Allowed baseline transitions:

```text
QUEUED    → RUNNING
QUEUED    → CANCELLED
RUNNING   → PAUSED
RUNNING   → VERIFYING
RUNNING   → QUEUED
RUNNING   → FAILED
RUNNING   → CANCELLED
PAUSED    → QUEUED
PAUSED    → CANCELLED
VERIFYING → COMPLETED
VERIFYING → QUEUED
VERIFYING → FAILED
```

Terminal states do not change silently. Requeueing a terminal operation creates an explicit new attempt or job according to policy.

## 8. Persistence

A job is persisted before the system claims that the work is durable.

Persist at least:

- intent;
- type;
- scope;
- authorization reference when required;
- state;
- retry policy;
- verification requirements;
- parent relationship;
- idempotency information.

Process memory may contain execution details, but it is never the sole source of lifecycle truth.

## 9. Worker Leasing

Workers obtain a renewable lease:

```text
worker_id
lease_until
heartbeat_at
```

A worker may update a job only while it owns the current lease.

If a lease expires:

1. mark the job as recovery candidate;
2. inspect whether external side effects may have occurred;
3. reconcile when possible;
4. retry only when idempotency/safety permits;
5. audit the recovery decision.

Lease expiry never means success.

## 10. Retry Classes

### TRANSIENT

Temporary network errors, service interruption, recoverable I/O failure, temporary resource pressure.

### RATE_LIMITED

Telegram/API throttling. Respect provider timing and bounded limits.

### PERMANENT

Invalid input, missing required resource, permission rejection, unsupported operation, malformed configuration.

### INTEGRITY

The executor produced an apparent result but verification failed.

### INTERNAL

Unexpected software error. Retry only according to an explicit policy; repeated identical failures should stop.

No infinite retries.

## 11. Backoff

Retries use bounded exponential backoff with jitter:

```text
base delay
→ exponential growth
→ jitter
→ maximum delay
→ retry ceiling
```

Provider-provided retry timing such as `Retry-After` takes precedence when safe.

## 12. Idempotency

Every job with external side effects must define repeat behavior.

Preferred strategies:

1. detect an already-completed result and verify it;
2. resume from a safe checkpoint;
3. reconcile partial state;
4. refuse repetition if safety cannot be established.

The worker must never assume that a crashed process implies that the external operation did not happen.

## 13. Verification

Verification is operation-specific.

Examples:

- message sent → verify expected message state where practical;
- media conversion → verify output exists, is readable, and meets required format;
- download → verify expected size/checksum where available;
- backup → verify artifact exists and can be validated;
- index → verify transaction completed and index consistency holds.

A job requiring verification cannot become `COMPLETED` before verification succeeds.

## 14. Parent/Child Jobs

Composite work may be represented as:

```text
ARCHIVE
├── DOWNLOAD
├── PROCESS
├── VERIFY
└── INDEX
```

The parent owns workflow intent. Children have independent durable identities.

Child scope cannot exceed the parent's authorized scope.

A parent is complete only when all required children satisfy their contracts.

## 15. Priority

Initial priority classes:

```text
CRITICAL
HIGH
NORMAL
LOW
BACKGROUND
```

Priority affects ordering only. It never bypasses:

- permissions;
- rate limits;
- resource limits;
- cancellation;
- verification;
- security policy.

## 16. Scheduling

The initial scheduler is deliberately simple:

1. recover abandoned jobs;
2. identify runnable jobs;
3. enforce concurrency/resource policy;
4. select by priority and age;
5. lease a job;
6. execute one bounded unit;
7. persist result;
8. verify if required;
9. schedule retry or finish;
10. release lease;
11. emit audit event.

A backlog is acceptable. Resource exhaustion is not.

## 17. Cancellation

Cancellation is persisted and cooperative.

A cancelled job:

- does not automatically resume;
- records cancellation reason;
- records partial/uncertain work where relevant;
- may require reconciliation;
- does not become successful merely because an executor stopped without error.

## 18. Offline Behavior

Network-dependent jobs should survive temporary connectivity loss.

The engine should preserve durable intent, classify the failure, schedule bounded retry, and avoid generating a request storm after reconnection.

## 19. Startup Recovery

At startup inspect:

- expired leases;
- RUNNING jobs without valid workers;
- stale retry schedules;
- incomplete verification;
- interrupted media work;
- orphaned temporary artifacts;
- parent jobs with inconsistent children.

Recovery is reconciliation, not blind replay.

## 20. Resource Safety

The scheduler respects:

- maximum workers;
- maximum concurrent Telegram/API requests;
- media CPU/RAM limits;
- download/upload concurrency;
- cache/disk capacity;
- per-plugin limits where needed.

Backpressure is preferred over unbounded queues.

## 21. Security Boundary

A job cannot elevate its own permissions or broaden its scope.

It cannot transform:

```text
read → write

non-destructive → destructive

one chat → all chats

one file → entire filesystem
```

without a new authorization/policy decision.

Arbitrary Python code must not be accepted as a durable job payload.

## 22. Failure Semantics

Use stable error codes rather than parsing arbitrary exception strings for scheduling decisions.

Examples:

```text
AUTH_DENIED
PERMISSION_DENIED
NOT_FOUND
INVALID_INPUT
RATE_LIMITED
NETWORK_ERROR
TIMEOUT
RESOURCE_LIMIT
INTEGRITY_FAILED
LEASE_EXPIRED
CANCELLED
UNSUPPORTED
INTERNAL_ERROR
```

Human-readable diagnostics are supplementary.

## 23. Auditability

Record material events:

```text
CREATED
AUTHORIZED
QUEUED
LEASED
STARTED
PROGRESS
PAUSED
RETRY_SCHEDULED
VERIFYING
VERIFIED
COMPLETED
FAILED
CANCELLED
RECOVERED
```

Audit records contain correlation/job IDs and safe metadata, never secrets.

## 24. Plugin Relationship

Plugins submit jobs through the Job Engine rather than owning their own unbounded scheduler when work must survive restart.

A plugin may maintain short-lived local tasks for ephemeral behavior, but it must not advertise such tasks as durable.

Existing schedulers are migrated incrementally.

## 25. Initial Implementation Boundary

The first Job Engine implementation must provide:

- SQLite persistence;
- migrations;
- canonical states/types;
- validated transitions;
- job creation/queueing;
- worker leases;
- bounded retries;
- failure classification;
- idempotency hooks;
- verification state;
- cancellation;
- startup recovery;
- audit events;
- tests for crash, retry, lease expiry, cancellation, duplicate prevention, and verification failure.

Do not begin with distributed queues or external infrastructure.

## Final Principle

> **A durable job represents work Astra has accepted responsibility for remembering. Its existence is never permission, its progress is never proof, and its executor's success is never verification.**
