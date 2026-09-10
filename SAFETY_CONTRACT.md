# AstraUserbot — Detailed Safety Contract

**Status:** Mandatory engineering contract  
**Version:** 2.0  
**Applies to:** Core, plugins, commands, events, jobs, HTTP, subprocesses, media, AI, storage, diagnostics

## 1. Fundamental Rule

Astra can act on a Telegram account and a local Linux environment. Therefore safety is an engineering property, not a UI feature.

> **When scope, authorization, ownership, or completion cannot be established, stop, surface uncertainty, and reconcile rather than guess.**

## 2. Side-Effect Classes

Every capability is classified as:

```text
READ_ONLY
REVERSIBLE_WRITE
EXTERNAL_SIDE_EFFECT
HIGH_IMPACT
DESTRUCTIVE
```

Classification controls authorization, retry, verification, audit, and resource limits.

## 3. Standard Operation Contract

```text
REQUEST
  ↓
VALIDATE
  ↓
AUTHORIZE
  ↓
SCOPE
  ↓
PLAN
  ↓
EXECUTE
  ↓
VERIFY
  ↓
AUDIT
  ↓
REPORT
```

Read-only operations may collapse stages but may not skip validation of untrusted input.

## 4. Authorization

Initial levels:

```text
OWNER
ADMIN
TRUSTED
PUBLIC
```

Capabilities refine access:

```text
telegram.read
telegram.write
telegram.moderate
account.control
filesystem.read
filesystem.write
subprocess.execute
network.request
media.process
ai.inference
security.manage
```

Authorization is centralized. A plugin declaring a capability does not automatically receive it.

## 5. Scope Binding

Every privileged operation binds authorization to a concrete scope:

```text
actor
operation
target
chat/account/filesystem scope
resource limits
```

The handler may not silently widen:

```text
message → chat
chat → all chats
file → directory tree
read → write
single target → bulk target set
```

## 6. Telegram Account Protection

Telegram is external authoritative state. Astra must not expose session material or silently change account authentication.

Broad operations such as mass deletion, permission changes, joins/leaves, posting, or account configuration require explicit scope and authorization.

Telegram rate limits are hard operational constraints. FloodWait must be respected; concurrency must be bounded.

## 7. Secrets

Never persist or emit:

```text
session strings/files
API keys
bot tokens
passwords
private keys
cookies with credentials
authorization headers
```

Secrets must not appear in source, normal logs, audit records, diagnostics, cache keys, job payloads, or AI prompts unless explicitly required and protected.

## 8. Command Safety

Every command has:

```text
owner
canonical name
aliases
permission
side-effect class
scope rules
```

Duplicate names/aliases are rejected.

Status/help/search/test commands are read-only unless their contract explicitly says otherwise.

## 9. Destructive Operations

Delete, purge, revoke, overwrite, promote, demote, mass-edit, mass-send, and similar actions require:

1. explicit authorization;
2. deterministic target resolution;
3. bounded execution;
4. appropriate rate limits;
5. verification where possible;
6. audit information.

Bulk destructive operations should support preview/dry-run where practical.

## 10. Dry Run

A dry run means:

```text
parse → validate → resolve → report
```

It must not perform the external mutation it previews.

## 11. Retry Safety

Retries use stable classes:

```text
TRANSIENT
RATE_LIMITED
TIMEOUT
RESOURCE_LIMIT
INTEGRITY
PERMANENT
INTERNAL
```

Never retry indefinitely. Before replaying an external mutation, determine whether the previous attempt may have succeeded.

## 12. Durable Work

Restart-sensitive work belongs to the Job Engine. The engine persists intent before execution and uses leases, retry limits, cancellation, verification, and recovery.

Lease expiry means uncertain outcome, not success or failure by assumption.

## 13. Filesystem Safety

Filesystem access uses canonical paths and configured roots:

```text
READ_ALLOWED
WRITE_ALLOWED
TEMP
PROTECTED
```

Reject traversal, ambiguous paths, symlink escapes where relevant, and writes outside policy roots.

User filenames are data, not trusted paths.

Temporary directories are unique per job and cleaned on success, failure, and cancellation. Startup orphan cleanup is required.

## 14. Subprocess Safety

Use argv-based execution through SubprocessService.

Required:

- no unsafe shell interpolation;
- timeout;
- cancellation;
- bounded stdout/stderr;
- explicit cwd;
- environment policy;
- executable/resource policy;
- safe logging.

FFmpeg, rclone, aria2c, OCR, transcription binaries, and system utilities are privileged capabilities, not generic user-controlled command execution.

## 15. Eval Boundary

Python eval is inherently privileged because plugins share one interpreter.

The implementation must:

- restrict invocation;
- serialize global stdout/stderr capture;
- enforce practical time/output limits;
- avoid claiming sandboxing;
- prevent secret leakage in returned values/errors;
- record failures safely.

A Python module boundary is not a security sandbox.

## 16. HTTP Safety

Shared HTTP service enforces:

```text
allowed schemes
URL policy
connect/total/read timeouts
redirect policy
response-size cap
per-host concurrency
retry rules
```

Arbitrary URLs require explicit policy. Internal/private targets and unbounded downloads must not be accidental behavior.

## 17. Media Safety

Every media job gets an isolated workspace.

Validate:

- source type;
- size;
- output type;
- output size;
- process lifetime.

Never select output by scanning a shared directory for the newest file.

Originals are not overwritten by default.

## 18. Cryptography

Encoding is not encryption.

SecretStore must use authenticated encryption such as AES-GCM or another reviewed primitive with appropriate key derivation, parameter storage, versioning, and integrity failure handling.

Cryptographic parameters must be centralized. Password handling must avoid retaining plaintext longer than necessary.

## 19. AI Boundary

AI output is untrusted data.

AI can assist with:

```text
summaries
classification
translation
search interpretation
tagging
planning
suggestions
```

AI cannot independently authorize:

```text
mass deletion
account control
credential changes
arbitrary filesystem writes
unrestricted subprocesses
security bypass
secret disclosure
```

Natural-language intent must become a typed deterministic request before execution.

## 20. Cache Safety

Cache is disposable. It must have:

- namespace;
- TTL/invalidation;
- capacity/size limits;
- safe serialization;
- stampede protection where needed.

Deleting cache must never delete authoritative data.

## 21. Database Safety

Use short SQLite transactions, foreign keys, migrations, and integrity checks.

Never perform network or long-running subprocess work inside a transaction.

Plugin code must not silently drop or rewrite another plugin's database.

## 22. Logging and Diagnostics

User-facing errors are safe summaries plus correlation IDs.

Logs may contain technical details only after redaction. Never log tokens, session strings, passwords, cookies, authorization headers, or full sensitive provider payloads.

Diagnostics are safe by default and bounded.

## 23. Plugin Failure Isolation

Plugins are not process-isolated. Nevertheless, their lifecycle resources are tracked:

```text
commands
event handlers
tasks
service references
setup state
shutdown state
```

A failed plugin must not leave half-registered commands or orphaned tasks.

## 24. Archiving and Logging Retention

Message archivers, reconstruction caches, logs, audit events, media artifacts, HTTP cache, and job history all require retention/capacity controls.

A broad exception that silently discards archival errors is forbidden in platform-managed persistence paths.

## 25. Monitoring

Monitoring is observational by default. `!health` or equivalent diagnostics must not silently mutate the system.

Automatic remediation requires a separate policy and audit contract.

## 26. Recovery

Recovery follows:

```text
detect
→ classify
→ inspect
→ reconcile
→ retry if safe
→ audit
```

Examples:

- uncertain message send → inspect before resend;
- expired job lease → reconcile;
- partial media output → inspect workspace;
- HTTP timeout → classify outcome uncertainty where mutation is possible;
- database error → preserve evidence.

## 27. Resource Safety

Every feature declares or inherits limits for:

```text
CPU
RAM
disk
network
Telegram requests
HTTP concurrency
subprocess output
job concurrency
media concurrency
AI context/output
```

Backpressure is preferred over unbounded queues.

## 28. Testing Contract

Permanent tests must cover:

- authorization denial;
- scope expansion denial;
- duplicate command rejection;
- secret redaction;
- path traversal;
- protected roots;
- subprocess timeout/cancel/output cap;
- HTTP timeout/size/redirect policy;
- media workspace isolation;
- eval serialization;
- retry exhaustion;
- lease recovery;
- verification failure;
- cache expiry;
- plugin setup failure reporting;
- destructive command preview/authorization.

## 29. Feature Readiness Checklist

Before accepting a new high-impact feature:

1. What can it mutate?
2. Who may invoke it?
3. What capability is required?
4. What is the exact scope?
5. What resources can it consume?
6. What happens on timeout?
7. What happens on duplicate invocation?
8. What happens after restart?
9. What is persisted?
10. What is logged?
11. How is success verified?
12. How is uncertain execution recovered?
13. Does it require paid infrastructure?

## 30. Mandatory Stop Conditions

Stop and report when:

```text
authorization is unknown
scope is ambiguous
credential state is uncertain
external mutation outcome is uncertain and cannot be reconciled
resource limits cannot be enforced
verification contract is missing for a required operation
```

## Final Rule

> **Astra is allowed to be powerful. It is not allowed to turn uncertainty into authority.**
