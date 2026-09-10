# AstraUserbot — Safety Contract

**Status:** Mandatory  
**Version:** 1.0  
**Scope:** All plugins, commands, event handlers, jobs, subprocesses, HTTP calls, media operations, AI integrations, and future interfaces

This is an engineering contract. A feature is incorrect if it violates these rules even when the resulting command technically succeeds.

## 1. Fundamental Rule

AstraUserbot has broad Telegram-account capabilities and may execute local programs, access files, call external services, and act asynchronously.

> **When scope, authorization, ownership, or safe completion cannot be established, stop rather than guess.**

## 2. Side-Effect Classification

Every operation must be classified as:

```text
READ_ONLY
REVERSIBLE_WRITE
HIGH_IMPACT
DESTRUCTIVE
EXTERNAL_SIDE_EFFECT
```

The classification determines required authorization, verification, audit, and retry behavior.

## 3. Controlled Lifecycle

Operations with meaningful side effects follow, as applicable:

```text
REQUEST
  ↓
VALIDATE
  ↓
AUTHORIZE
  ↓
PLAN
  ↓
EXECUTE
  ↓
VERIFY
  ↓
AUDIT
```

Read-only inspection may omit authorization and mutation stages.

## 4. Telegram Account Protection

The userbot's Telegram account/session is protected state.

The system must not silently:

- expose session material;
- rotate or invalidate credentials;
- send uncontrolled message floods;
- mass-delete or mass-edit messages without explicit command scope;
- add/remove administrators without authorization;
- join/leave groups or channels as a hidden side effect;
- perform account-wide actions from a narrowly scoped command;
- bypass Telegram rate limits.

## 5. Secrets

Secrets include:

- `API_ID`/`API_HASH` where sensitive handling applies;
- session strings/files;
- bot tokens;
- provider API keys;
- passwords;
- private keys;
- cookies/auth headers;
- database credentials.

Secrets must never be committed, emitted into ordinary logs, included in audit records, sent to AI providers unnecessarily, or returned as command output.

## 6. Command Authorization

Authorization must be centralized.

Initial conceptual levels:

```text
OWNER
ADMIN
TRUSTED
PUBLIC
```

Commands declare required permissions/capabilities.

The current convention that userbot self/outgoing commands are owner-scoped is useful compatibility behavior, but it must not be the only long-term authorization mechanism.

## 7. Scope Binding

Authorization applies to the operation that was reviewed.

A handler cannot silently expand:

```text
one message → entire chat
one chat → all chats
one file → filesystem
one target → every target
read → write
```

A materially changed scope requires a new authorization decision.

## 8. No Hidden Side Effects

Commands advertised as status, inspect, search, help, test, or dry-run must not silently mutate state.

Examples:

- health checks do not restart services unless explicitly requested;
- search does not edit messages;
- indexing does not reorganize files;
- duplicate detection does not delete content;
- dry-run does not execute;
- diagnostics do not leak secrets.

## 9. Destructive Operations

Operations that can delete, overwrite, mass-edit, mass-delete, revoke, promote, demote, purge, or otherwise create difficult-to-reverse effects require:

1. explicit command scope;
2. authorization;
3. deterministic target resolution;
4. bounded execution;
5. verification where possible;
6. audit information.

For bulk destructive operations, provide a dry-run/preview before apply whenever practical.

## 10. Telegram Rate Limits

Telegram limits are part of the system contract.

The userbot must:

- respect FloodWait responses;
- bound concurrency;
- avoid request storms;
- use retries only when safe;
- avoid repeated scans when cached state is sufficient;
- apply sender/chat cooldowns where automatic replies could become noisy.

The system must never attempt to bypass platform limits.

## 11. Retry Safety

Retries are classified:

```text
TRANSIENT
RATE_LIMITED
PERMANENT
INTEGRITY
INTERNAL
```

Never retry indefinitely.

Before retrying an externally visible mutation, determine whether the previous attempt may have succeeded.

## 12. Job Durability

Long-running work uses the durable Job Engine.

A process crash must not silently erase accepted work or mark it complete.

Worker lease expiry requires reconciliation before retrying an operation with external side effects.

## 13. Filesystem Safety

Filesystem operations must:

- canonicalize paths;
- enforce allowed roots;
- reject traversal/ambiguous paths;
- avoid accidental writes outside configured workspaces;
- use unique temporary directories;
- clean temporary artifacts in success and failure paths;
- enforce file/size limits where appropriate.

A user-provided filename is data, not a trusted path.

## 14. Subprocess Safety

External commands must use argv-based execution through the shared SubprocessService.

Requirements:

- no `shell=True` for user-controlled input;
- timeout;
- cancellation cleanup;
- output limits;
- resource limits;
- safe logging;
- explicit capability/policy checks.

Powerful tools such as FFmpeg, rclone, aria2c, OCR, transcription binaries, and system utilities must not become unrestricted command execution surfaces.

## 15. Python Evaluation

The existing eval capability is intentionally powerful and therefore must be treated as a privileged operation.

It must:

- remain owner-restricted;
- serialize concurrent evaluation/output capture;
- have execution/output limits where practical;
- never claim to be a security sandbox;
- audit failures safely;
- avoid leaking secrets through returned globals or tracebacks.

Arbitrary Python execution cannot be made safe merely by changing the UI.

## 16. HTTP Safety

Network features must use controlled HTTP clients.

The system should enforce:

- URL validation;
- HTTP/HTTPS policy;
- timeouts;
- response-size limits;
- redirect policy where appropriate;
- per-host concurrency;
- retry classification;
- secret redaction.

Features accepting arbitrary URLs must not accidentally become unbounded downloaders or internal-network access paths without an explicit policy decision.

## 17. Media Safety

Media processing must use isolated per-job workspaces.

Requirements:

- unique input/output paths;
- bounded downloads;
- MIME/format validation;
- subprocess timeout;
- cleanup on failure;
- output size limits;
- cancellation support.

Selecting "the newest file" from a shared directory is not a valid job-output identity mechanism.

## 18. Cryptography

Encoding is not encryption.

Secret storage must use an authenticated encryption design such as AES-GCM or another reviewed authenticated-encryption primitive with appropriate key derivation.

A plaintext/base64 vault must never be presented as encrypted storage.

Cryptographic parameters must be centralized and documented.

## 19. AI Safety Boundary

AI output is untrusted input.

AI may:

- summarize;
- classify;
- suggest tags;
- propose commands;
- translate natural-language requests;
- assist search;
- recommend actions.

AI may not independently authorize:

- mass deletion;
- account permission changes;
- credential changes;
- arbitrary filesystem mutation;
- unrestricted subprocess execution;
- security-policy bypass;
- secret disclosure.

AI suggestions must pass deterministic validation and authorization before execution.

## 20. Cache Safety

Cache data is derived and disposable.

A cache must have:

- bounded size;
- expiry/invalidation;
- namespace isolation;
- safe serialization;
- stampede protection for expensive refreshes where necessary.

Cache loss must not be treated as data loss.

## 21. Logging and Diagnostics

Logs must be useful without becoming a secret dump.

Redact:

- tokens;
- passwords;
- session material;
- authorization headers;
- API keys;
- private paths where disclosure is unnecessary;
- raw provider responses when they may contain credentials.

User-facing errors should contain a safe summary and correlation ID, not raw traceback text.

## 22. Plugin Isolation

A plugin failure must not silently corrupt global runtime state.

Plugins must own and clean up their registrations/tasks/resources.

The Plugin Manager tracks:

- lifecycle state;
- command ownership;
- task ownership;
- setup failure;
- shutdown failure.

## 23. Account Archival and Logging

Message archiving/logging features must have explicit retention and capacity controls.

A broad `except Exception: pass` around durable archival is not acceptable for the platform implementation because it hides operational failures.

Failures should be classified, logged safely, and surfaced through diagnostics.

## 24. Monitoring

Health monitoring observes the system. It does not silently grant itself remediation authority.

Automatic remediation, if ever introduced, must have explicit policy, bounded scope, and auditability.

## 25. Recovery

Recovery must prefer reconciliation over blind replay.

Examples:

- unknown message-send outcome → inspect before resend when possible;
- partial media output → inspect/clean workspace before retry;
- expired job lease → reconcile external state;
- provider timeout → classify as uncertain rather than assume failure;
- database error → preserve evidence rather than silently discard it.

## 26. Testing Requirements

Safety tests must permanently cover:

- duplicate command detection;
- permission rejection;
- scope expansion rejection;
- destructive command preview/authorization;
- Telegram rate-limit handling;
- secret redaction;
- protected filesystem roots;
- path traversal rejection;
- subprocess timeout/cancellation;
- bounded subprocess output;
- concurrent eval serialization;
- HTTP timeout/size limits;
- media workspace isolation;
- retry exhaustion;
- job lease recovery;
- verification failure;
- cache expiry;
- plugin setup failure reporting.

## 27. Feature Readiness Questions

Before implementation of any new feature, answer:

1. What side effects can it cause?
2. Who can invoke it?
3. What capability does it require?
4. What resources can it consume?
5. What happens on timeout?
6. What happens on duplicate invocation?
7. What happens after process restart?
8. What data is persisted?
9. What is logged?
10. How is success verified?
11. How is failure recovered?
12. Can the feature operate without paid infrastructure?

If these are undefined for a high-impact feature, the feature is not ready.

## Final Safety Principle

> **AstraUserbot should be powerful by capability, conservative by default, explicit about side effects, and honest about uncertainty.**
