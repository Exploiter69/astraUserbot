# AstraUserbot — Phase 7 Readiness Audit

**Audit target:** `main` after Phase 6 and durable-job hardening  
**Purpose:** verify the platform is ready to begin the canonical Phase 7 Media Platform without silently carrying forward architecture gaps.

## Executive Result

**Status: READY TO START PHASE 7 AFTER LOCAL REGRESSION PASS**

Phase 6 passed its baseline gate with 73/73 tests and compile validation. The pre-Phase-7 audit found one material contract gap in the durable JobEngine: expired/interrupted work was previously requeued automatically even though the job contract explicitly requires conservative handling of unknown external outcomes.

That gap has now been corrected:

- `UNCERTAIN` is a first-class job state;
- expired leases enter `UNCERTAIN` instead of `QUEUED`;
- active jobs interrupted by worker shutdown enter `UNCERTAIN`;
- cancellation of active work enters `UNCERTAIN`;
- uncertain work requires explicit `requeue_uncertain()` after reconciliation;
- regression coverage was added for expiry, explicit requeue, and shutdown recovery.

The local suite must be rerun after pulling these commits before the Phase 7 implementation gate is considered verified.

---

## 1. Platform Foundation

| Area | Result | Notes |
|---|---|---|
| Plugin discovery/lifecycle | PASS | Deterministic discovery, dependency ordering, setup/shutdown, ownership tracking. |
| Command router | PASS | Collision detection, ownership, metadata, safe errors. |
| ACL/PMGuard ownership | PASS | ACL exclusively owns `.block`/`.unblock`; PMGuard no longer registers duplicates. |
| TaskSupervisor | PASS | Ephemeral tasks are supervised and bounded. |
| ApplicationContext | PASS | Shared services have explicit lifecycle. |
| HTTP | PASS | Shared session, limits, retries, cancellation. |
| Subprocess | PASS | argv execution, timeout, bounded output, cancellation. |
| Workspace | PASS | Per-operation workspace and cleanup primitives available. |
| Cache | PASS | L1/L2/L3, TTL, bounds, cleanup, stampede protection. |
| Storage | PASS | SQLite WAL, FK, migrations, integrity and backup. |
| Job durability | PASS after hardening | Unknown execution outcomes are now explicit. |

---

## 2. JobEngine Hardening Findings

### Fixed before Phase 7

**Unknown outcome replay risk.**

Previously, `recover_expired()` changed an expired `RUNNING` job directly back to `QUEUED`. That could replay a non-idempotent external action after the worker had already performed the side effect but disappeared before recording completion.

The implementation now uses:

```text
RUNNING
   ↓ lease expires / worker disappears
UNCERTAIN
   ↓ explicit reconciliation
QUEUED
   ↓ normal execution
RUNNING
```

This now matches the job contract's conservative recovery rule.

### Deliberately deferred

**Independent resource-class concurrency.** The current worker loop executes one job at a time, so total live job execution is bounded. `resource_class` is persisted metadata but does not yet provide independent limits such as `MEDIA=1`, `NETWORK=4`, or `TELEGRAM=2`.

This is intentionally deferred into Phase 7 because the MediaService needs explicit heavy-work concurrency policy before media jobs are allowed to run concurrently.

**Parent/child orchestration API.** Parent IDs exist and are persisted, but there is not yet a complete child lifecycle/orchestration API. No current Phase 7 media design should depend on implicit parent semantics.

**Audit-event unification.** Job lifecycle events are durable in `job_events`; the generic `audit_events` table exists separately. A later observability/audit pass can define when both are required.

**Migration SQL parser.** The current migration set is simple and deterministic. Semicolon splitting remains a future hardening item if migrations require complex SQL bodies.

---

## 3. Media Platform Audit — Phase 7 Entry Point

### Current consumers

```text
plugins/media/ffmpeg.py
plugins/advanced/mediaflow.py
plugins/media_ops/video.py
plugins/media_ops/speech.py
plugins/media_ops/stream.py
plugins/media/aria2.py
plugins/media/rclone.py
```

### Current good foundations

- FFmpeg/media consumers already route subprocess execution through the shared `SubprocessService` via `helpers.shell`.
- `stream.py` and `aria2.py` already use `WorkspaceService` where the application context is available.
- `stream.py`, `aria2.py`, `speech.py`, and `mediaflow.py` perform `finally` cleanup.
- Phase 6 added isolated stream workspaces and normalized cleanup.

### Remaining Phase 7 work

**A. One MediaService contract**

Centralize:

```text
download
inspect
validate
convert
extract
thumbnail
transcribe-hook
prepare-upload
cleanup
```

**B. Job-owned workspaces**

`ffmpeg.py`, `mediaflow.py`, `video.py`, and `speech.py` still use shared `data/cache` paths directly. These must move to job/operation workspaces.

**C. Deterministic outputs**

`stream.py` currently finds the newest non-temporary file in its isolated workspace. This is much safer than the old shared-cache behavior, but Phase 7 should return explicit output manifests rather than infer the result from filesystem ordering.

**D. argv-only FFmpeg execution**

`mediaflow.py` and `video.py` construct command strings. The shared subprocess service does not invoke a shell and currently tokenizes strings with `shlex`, so this is not a shell-injection path. Nevertheless, Phase 7 should construct explicit argv arrays so filenames and filter arguments cannot be corrupted by quoting edge cases.

**E. Resource limits**

Phase 7 must define bounded media input/output sizes, execution time, temporary workspace size, and concurrency by workload class.

**F. Cleanup semantics**

Every path must clean the job-owned workspace, including download failure, FFmpeg failure, upload failure, cancellation, and process shutdown.

**G. Verification**

A zero exit code is not sufficient. Media completion should verify expected output existence, readability, format/metadata where appropriate, and successful Telegram promotion/upload before declaring durable completion.

**H. Rclone boundary**

`rclone.py` accepts user-provided rclone arguments. It is already routed through the shared subprocess service in the normal runtime, but Phase 7 should define a capability/policy boundary around permitted rclone operations rather than treating arbitrary arguments as a generic media API.

---

## 4. AI Audit — Deferred to Canonical Phase 8

Existing AI usage was inspected because it is an important future migration, but **AI Gateway is not Phase 7 work**.

Current provider coupling is concentrated in:

```text
plugins/ai/groq_client.py
plugins/ai/ask.py
plugins/ai/summarize.py
plugins/ai/transcribe.py
```

The current client reads `GROQ_API_KEY` and calls Groq's OpenAI-compatible endpoints. The existing plugins import that client directly.

Current configuration already exposes:

```text
GROQ_API_KEY
GEMINI_API_KEY
OPENROUTER_API_KEY
```

The architecture documents an eventual provider-independent gateway, but no local LLM should be treated as a deployment requirement for the current AstraUserbot host.

Phase 8 should therefore extract the current Groq behavior behind an adapter/gateway first. Local Ollama/llama.cpp remains optional architecture, not a prerequisite.

---

## 5. Runtime/Lifecycle Audit

### PASS

- `main.py` creates the ApplicationContext before plugin loading.
- Services start before plugins consume them.
- Plugins shut down before shared context teardown.
- ApplicationContext closes services in reverse start order.
- TaskSupervisor rejects new work after shutdown and cancels stragglers.
- JobEngine now converts active interrupted work to `UNCERTAIN` during close.
- HTTP and other shared services have restart/close tests.

### Follow-up

The legacy `core/bootstrap.py` shutdown path still exists for compatibility and owns the legacy `TaskSupervisor`/database close behavior. It should remain compatibility-only until legacy callers are fully migrated.

---

## 6. Infrastructure Bypass Audit

### Shared infrastructure is authoritative for current runtime

- HTTP: `HttpService` is the runtime authority; `helpers/net.py` is a compatibility wrapper.
- Subprocess: `SubprocessService` is the runtime authority; `helpers/shell.py` is a compatibility wrapper.
- Workspace: service exists and is already used by stream/aria2.
- Storage: platform persistence is owned by `StorageService`.
- Cache: platform cache is owned by `CacheService`.

### Remaining intentional/known legacy paths

- media consumers still own their own file naming/workspace conventions;
- some legacy plugin databases remain until individually migrated;
- `astra.py` contains legacy subprocess helpers and should not be treated as the Phase 7 media service boundary;
- direct `aiohttp.ClientSession` use remains in the Telegra.ph publishing path in `plugins_bundle.txt`/`plugins/system/help.py` and should be migrated during the later network/plugin migration pass.

No new core service bypass is required to begin Phase 7.

---

## 7. Security Boundary Audit

### PASS / existing controls

- secrets are environment-backed and `.env` is excluded from source control;
- SecretStore provides authenticated encryption for migrated vault secrets;
- command router has a safe error boundary;
- subprocess execution is argv-based and bounded;
- HTTP has response limits and timeouts;
- WorkspaceService enforces canonical roots and file limits;
- AI is documented as non-authoritative;
- eval is intentionally privileged and its stdout capture is serialized/bounded.

### Phase 7 requirements

MediaService must not turn arbitrary media options into unrestricted filesystem or subprocess authority. It should expose narrow operations, validate paths through WorkspaceService, enforce resource limits, and preserve owner authorization at the command/job boundary.

---

## 8. Documentation Consistency

The roadmap and Job Model were updated alongside the durable-job hardening so the documented recovery contract matches the implementation.

Remaining documentation cleanup is non-blocking:

- legacy compatibility paths can be removed after migration;
- resource-class concurrency should be documented again once Phase 7 introduces it;
- Phase 8 AI docs should be updated when the gateway is actually implemented rather than prematurely claiming provider independence.

---

## 9. Phase 7 Gate Definition

Do not declare Phase 7 complete until all of the following are true:

```text
MediaService exists
    ↓
all seven listed media consumers use it
    ↓
unique job/operation workspaces are authoritative
    ↓
outputs are explicit/deterministic
    ↓
media resource limits are enforced
    ↓
cleanup works on success/failure/cancel/shutdown
    ↓
media verification is explicit
    ↓
concurrent media regression tests pass
    ↓
full regression suite passes
```

## Final Readiness Decision

**READY TO BEGIN PHASE 7 after the local regression suite passes.**

The correct next implementation is **Media Platform**, not AI Gateway and not local LLM deployment.
