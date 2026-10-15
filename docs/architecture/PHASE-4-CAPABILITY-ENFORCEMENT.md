# AstraUserbot Phase 4 — Capability Enforcement Design

**Revision:** 3  
**Status:** Approved design; implementation authorized in the sequence below.  
**Scope:** Design contract for Phase 4. Owner-facing plugin commands, broad plugin adoption, Phase 5 SDK/DX, and RAG are deferred.

## 1. Problem statement

### 1.1 Governing constraint

> In-process capability handles are governance, not a sandbox. A Python plugin sharing the process can still import os, reach sys.modules, or access shared state through a global. Phase 4 enforces the supported plugin API, default-deny at the service boundary, with audit. It does not contain a malicious plugin. Real containment requires a process boundary and is a separate build, out of scope for Phase 4.

This constraint governs every section. Capability checks authorize supported APIs; they do not contain arbitrary malicious Python.

### 1.2 Current access model — source-verified

The plugin manager imports ordinary in-process Python modules and preserves the legacy setup(client) entry point. Relevant source:
- core/plugins/manager.py — discovery/import, metadata, lifecycle, setup context, rollback journal.
- core/context.py — process-wide ApplicationContext and service registry.
- core/registry.py — command registration and command metadata.
- core/sdk.py — plugin metadata shape.
- core/plugins/contract.py — metadata normalization.

Current access path:

    Plugin Python module
        ├── setup(client) ───────────────► Telegram client
        ├── imports core modules ────────► Python process / shared module state
        ├── get_application_context() ──► ApplicationContext
        │                                  └── get("service") ──► service object
        ├── direct service imports ─────► service implementations
        └── register_cmd(...) ──────────► command registry / client event handlers

Current security reality: plugins are ordinary in-process modules with full access to the client, services, DB, network, filesystem. This describes the effective trust boundary, not a claim that every plugin uses every resource.

### 1.3 Existing mechanisms and gap — source-verified

- Plugin metadata includes a capabilities field, normalized into PluginRecord.capabilities.
- register_cmd supports permission, operation_class, required_capabilities, and other operation metadata.
- ApplicationContext registers named services, including Telegram, HTTP, subprocess, jobs, secrets, AI, storage, and others.
- The manager tracks plugin lifecycle and registrations; Phase 3c provides tracked_task, tracked_job, tracked_resource, and a per-attempt setup journal.

Metadata does not itself enforce per-plugin grants at the service boundary. For example, ApplicationContext.get(name) returns the registered service object directly. Command permissions and operation metadata are not a substitute for service authorization.

### 1.4 Phase 4 changes and limits

Phase 4 introduces an enforceable capability vocabulary, persistent owner-only grants, effective-grant resolution, service-boundary checks, a structured audit stream, and exactly two proven migration paths: one read-only plugin in ENFORCED and one non-migrated plugin in LEGACY_UNDECLARED.

It does not sandbox Python, rewrite all 56 plugins, redesign the plugin-manager lifecycle, or reopen Phase 3b/3c.

## 2. Capability model

### 2.1 Principles

Capabilities identify meaningful authority at an actual enforcement boundary. One blanket capability is too coarse; per-method permissions are too fine. Begin with resource domains and materially different effects. Names are stable API identifiers.

### 2.2 Initial vocabulary — exactly 11 capabilities

Design proposal; each boundary must be verified before its capability is treated as enforced.

| Capability | Intended authority | Required enforcement boundary |
|---|---|---|
| telegram.read | Read permitted Telegram messages/state | Supported Telegram read facade |
| telegram.write | Send or mutate Telegram state through supported APIs | Supported Telegram mutation facade |
| network.external | External network requests through supported APIs | Supported HTTP/network service |
| fs.read | Read files through supported APIs | Supported filesystem/workspace facade |
| fs.write | Create, modify, or delete files through supported APIs | Supported filesystem/workspace facade |
| subprocess | Start/control external processes through supported APIs | SubprocessService |
| jobs.enqueue | Enqueue supported durable jobs | JobEngine facade |
| ai.remote | Invoke remote AI providers | Remote-provider boundary in AIService |
| ai.local | Invoke configured local AI services | Local-provider boundary in AIService |
| vault.read | Read secrets through supported API | SecretStore |
| vault.write | Create/update/delete secrets through supported API | SecretStore |

Deferred until plugin-facing boundaries are confirmed: db.own, db.shared.read, scheduler, intel.write, cases.write.

**A capability that has no enforced boundary is worse than no capability, because it implies governance that does not exist. Do not ship a grant that cannot be enforced.** Deferred names must not be represented as effective grants in Phase 4.

Granularity notes:
- telegram.write remains broad initially; existing command operation metadata continues to distinguish destructive actions.
- network.external covers supported network APIs, not direct imports of networking libraries.
- fs.read/fs.write cover supported file facades, not arbitrary Python filesystem calls.
- db.own must wait for a genuine enforceable plugin namespace.
- scheduler, intel.write, and cases.write must wait for verified boundaries.

### 2.3 Denial behavior

A protected call outside the effective grant set raises typed CapabilityDeniedError; no silent no-op or fake success. Stable fields should include code=CAPABILITY_DENIED, plugin, capability, operation, and correlation ID where available. Messages and audit must not expose secrets or protected payloads.

### 2.4 Default-deny and legacy compatibility

Two explicit states:
- LEGACY_UNDECLARED: existing undeclared plugin retains temporary compatibility behavior and receives an actionable deprecation warning.
- ENFORCED: plugin is governed by declaration and owner-approved grants. A new undeclared plugin receives no privileged capabilities.

Do not infer legacy status from an empty declaration. New undeclared plugins do not inherit unrestricted access by default. Legacy compatibility is explicit and temporary.

## 3. Grant mechanism

### 3.1 Declaration and approval are separate

The existing module metadata convention is retained. Keep separate:
1. Declared capabilities (plugin request).
2. Owner-approved grants (owner authorization).
3. Effective capabilities (for an enforced plugin, declared ∩ approved).

The owner cannot grant an undeclared capability. Unknown names are rejected.

### 3.2 Persistent grant store — required storage and migration constraints

**Phase 4 requirement:** use the existing storage service, implemented through additive migrations in core/services/storage.py. Use the same integrity, checksum, and concurrency guarantees as the rest of the schema. Do not introduce a separate SQLite database file or a parallel persistence path. The migration must be additive; existing rows remain untouched.

The current source inspection does not establish an existing dedicated capability-grant store, so implementation must add it deliberately through the existing storage/migration system rather than treating plugin metadata as the grant database.

Store canonical plugin identity, approved capability identifiers, schema/version information, grant/revocation timestamps, and owner authorization provenance/reason where available. Do not duplicate secret values.

Grant mutation is owner-only using the existing owner authorization mechanism. Plugins cannot grant themselves capabilities, other plugins cannot grant them, and command registration metadata does not grant authority.

### 3.3 Grant changes

- Adding a grant requires a recognized declared capability, owner authorization, persistence, and controlled reload before the new grant is effective.
- Revocation is persisted immediately and must block subsequent supported calls once the policy update is committed; controlled reload reconciles plugin state.
- Reload failure must not restore a revoked grant.
- Invalid declarations/policy must not silently fall back to legacy mode.

### 3.4 Owner-facing commands — deferred

Not part of Phase 4. A follow-on after the enforcement core is proven may add:
- .plugin grants <plugin>
- .plugin grant <plugin> <capability>
- .plugin revoke <plugin> <capability>

The future view can show declared, approved, effective, and pending-reload state. Phase 4 delivers the grant store and enforcement, not this UI.

## 4. Enforcement point

### 4.1 Dual-layer design

Use both a scoped plugin handle/SDK facade and authoritative service-boundary checks. The service boundary is authoritative. A handle-only design is insufficient because plugins can access the context, import services, or retain client references. Service-only enforcement leaves the supported API unclear. Neither layer prevents arbitrary Python from bypassing both.

### 4.2 Current service access patterns — source-verified

ApplicationContext.get(name) returns registered service instances; get_application_context() exposes the process-wide context. Services include storage, HTTP, subprocess, Telegram, jobs, secrets, AI, and others.

Representative current patterns:

    context = get_application_context()
    jobs = context.get("jobs")
    await jobs.enqueue(...)

and direct client use:

    await client.send_message(...)

These are representative, not exhaustive. Direct client calls, imports, and helpers bypassing supported facades are migration hotspots.

### 4.3 Scoped handle and trusted-core identity

Keep setup(client) unchanged. The manager already uses ContextVar for current plugin, manager, and setup journal. The proposal is to activate a manager-owned capability context around setup and resolve the scoped handle from it; reset context in finally.

**Before Step 1 ships, trusted-core identity must be defined and tested.** Framework-owned service calls—including command registry, job worker, archive engine, background tasks, and reconciler execution from core-owned code—run under an explicit trusted-core identity, not as a plugin with empty grants.

Plugin-owned callbacks invoked by the framework must not inherit unrestricted core authority. The implementation must explicitly distinguish core-owned code from plugin-owned callbacks, and tests must prove existing framework paths continue to function under that identity. Do not use a blanket core bypass for plugin-owned work.

ContextVar is execution-context association, not isolation. Retained references, shared state, direct imports, and arbitrary Python remain bypasses. This design is governance, not a sandbox.

### 4.4 Check ordering, cache, and invalidation

For each protected operation:
1. Resolve caller identity and policy mode.
2. Resolve required capability.
3. Check effective grants.
4. Record authorization outcome.
5. If denied, raise CapabilityDeniedError.
6. Only then perform the protected side effect.

**Effective-grant lookup must not hit storage on the hot path.** Resolve grants at plugin load or first use and cache them in memory per plugin. A protected call must not perform a disk read to determine authorization.

**Cache invalidation rule:** on every successful grant mutation, invalidate or atomically replace that plugin's cached effective-grant entry before subsequent protected calls can use it. Controlled reload also invalidates/rebuilds the cache. Revocation must not remain usable from stale cache after the grant mutation commits; do not wait until a later reload to enforce a revocation. Failed policy resolution must not turn into an implicit allow.

For high-impact mutations, fail closed if the authorization decision cannot be established. Audit delivery failure and authorization failure must remain distinguishable. A denial must precede side effects.

### 4.5 Existing command metadata retained

Keep permission, operation_class, required_capabilities, network, durable_job, destructive-operation metadata, and other existing registration fields. Extend their integration: validate capability names at registration, preserve command permission checks, and independently enforce service-level requirements. Command metadata is not itself a grant.

## 5. Migration and backward compatibility

### 5.1 Legacy policy

Existing undeclared plugins remain explicitly LEGACY_UNDECLARED during migration, with startup warnings identifying the plugin, stating enforcement is inactive, and giving concrete next steps: inventory service usage, declare capabilities, obtain owner approval, test, and migrate to ENFORCED.

Warnings should be bounded (e.g. once per plugin per startup plus a summary), not emitted on every call. Invalid metadata/policy must not silently trigger legacy mode.

### 5.2 Future adoption roadmap — not Phase 4

This six-tier order belongs to a later adoption phase, not Phase 4:
1. Read-only plugins.
2. OSINT/intelligence plugins.
3. Media plugins.
4. Jobs and automation plugins.
5. Security plugins.
6. System/eval plugins.

Order within tiers depends on source-verified usage. Phase 4 does not rewrite all 56 plugins or migrate all tiers.

### 5.3 Phase 4's only two migrations

Phase 4 ships vocabulary + grant store + service-boundary checks + audit + one proven migration plus a verified legacy path:
- Migrate one read-only plugin (candidate .ping or .help, chosen only after source inspection) to declared capabilities under ENFORCED.
- Prove a non-migrated plugin continues under LEGACY_UNDECLARED with the actionable deprecation warning.

The read-only plugin must declare only real requirements from the 11-capability vocabulary. Its granted operation must succeed; a deliberately undeclared/ungranted operation must raise CapabilityDeniedError, leave no side effect, and produce audit records for both outcomes. The legacy plugin must continue existing behavior and must not be silently promoted or misclassified.

Illustrative metadata shape:

    plugin_name = "plugins.example"
    plugin_version = "1.0.0"
    capabilities = ("telegram.read",)

## 6. Interaction with Phase 3b and Phase 3c

Compatibility only. Do not reopen or redesign either phase.

### 6.1 Phase 3b: effect classes and reconcilers

Job effect classification and reconciler registration remain governed by the existing contract. Separate job submission authority from reconciler registration:
- jobs.enqueue authorizes durable job submission through its service boundary.
- Reconciler registration follows existing lifecycle/job-contract rules and does not grant enqueue or Telegram-write authority.
- Core-owned reconciler code uses explicit trusted-core identity.
- Plugin-owned reconciler code must not gain unrestricted core authority merely because the framework invokes it.

A plugin with jobs.enqueue must be able to register a valid reconciler and enqueue a tracked job. A plugin without it must be denied enqueue, but not denied valid reconciler registration solely because it lacks enqueue authority. Verify exact registration paths during implementation.

### 6.2 Phase 3c: tracked resources and journal

Existing APIs remain intact:
- tracked_task(...): no blanket jobs.enqueue requirement; apply the authority required by the actual task API.
- tracked_job(...): requires jobs.enqueue before enqueueing.
- tracked_resource(...): check the capability required by its factory/operation before creation.

On denial, raise before creating the resource and do not record a journal entry for a nonexistent resource. Successful creations use the existing journal. Preserve reverse-order cleanup and existing UNCERTAIN semantics. Do not change setup signature or Phase 3c behavior.

## 7. Audit and observability

### 7.1 Audit stream — Phase 4 deliverable

Record granted and denied capability checks with timestamp, plugin identity, capability, operation, sanitized call site, outcome, policy mode, correlation ID when available, and reason code. Never record secrets, full messages, authentication headers, file contents, or unrestricted payloads.

A GRANTED record means authorization passed; it is not proof the side effect later succeeded unless a separate completion event confirms it.

### 7.2 Owner-facing audit command — deferred

Not part of Phase 4. A follow-on may add .plugin audit <plugin> and .plugin grants <plugin> to display declared, approved, effective, and observed capabilities. Unobserved grants are review candidates, not auto-revocation candidates.

Phase 4 supplies the stream and records only; no owner-facing .plugin commands ship.

### 7.3 Noise and failures

Aggregate repeated denials by plugin/capability/operation. Surface unexpected denials as operation failures with a correlation reference. Notify the owner for repeated policy errors/high-impact patterns, not every denial. Summarize legacy plugins at startup.

For high-impact mutations, fail closed if authorization cannot be established. Audit delivery failure must not bypass authorization.

## 8. Failure and rollback

### 8.1 Denial before side effect

Denied enqueue creates no job/journal entry; denied Telegram mutation is not sent; denied file write does not modify a file; denied vault write does not change a secret; denied subprocess/network operations do not reach their supported boundary. Authorization success does not guarantee later operation success.

### 8.2 Enforcement rollback

Use an explicit owner-controlled and audited setting to disable enforcement if necessary. Preserve declarations, approved grants, and diagnostic audit history. Mark enforcement disabled visibly; do not delete or rewrite grants. Re-enable only with policy validation.

Rollback must never silently restore “every plugin can do everything” as an implicit fallback. Disabling enforcement is an explicit operational state, not a new policy or sandbox.

### 8.3 Invalid policy

Unknown capabilities, malformed grants, and unresolved policy must not silently move an enforced plugin to LEGACY_UNDECLARED. Deny protected operations and report policy error.

## 9. Test plan and acceptance

### 9.1 Capability boundary tests

For each of the 11 capabilities, test a granted representative operation, a denied call raising CapabilityDeniedError, no protected side effect on denial, and the correct audit record. Test real service boundaries, not only a helper. If a real boundary is not enforceable/testable, that capability does not ship.

### 9.2 Grant store/default-deny tests

- New undeclared plugin gets no privileged capabilities.
- Declared-only and approved-only capabilities do not authorize; effective grants equal declared ∩ approved.
- Owner-only mutation persists; plugins cannot self-grant; undeclared grants are rejected.
- Grant reads/writes and cache invalidation work.
- Migration is additive and idempotent; existing rows are untouched.
- Revocation invalidates the cached policy before subsequent protected calls.
- Invalid policy does not fall back to legacy.

### 9.3 Phase 3b/3c compatibility tests

- Plugin with jobs.enqueue registers a valid reconciler and enqueues a tracked job.
- Plugin without it cannot enqueue through tracked_job.
- Denied job creation leaves no job/journal entry.
- Tracked task/resource use the appropriate capability rules.
- Existing cleanup order and uncertain-job semantics remain intact.
- Missing enqueue authority alone does not block valid reconciler registration.

### 9.4 Audit and trusted-core tests

- Granted and denied calls produce distinct structured records with correct fields and no secrets.
- Audit storage failure never bypasses authorization; high-impact calls fail closed if authorization cannot be established.
- Existing framework paths—command registry, job worker, and at least one background task—execute under explicit trusted-core identity without accidental capability denial.
- Plugin-owned callbacks do not inherit unrestricted core authority.
- Enforcement rollback preserves declarations and grants and is visible/audited.

### 9.5 Isolation honesty test

Keep test_capability_handles_do_not_sandbox_direct_python_access. A harmless controlled fixture demonstrates that a plugin bypassing the supported handle and directly accessing an imported module/process resource is not blocked by the handle. The test passes by reproducing and documenting this limitation, not by pretending it is prevented. This is governance, not a sandbox.

### 9.6 Two end-to-end acceptance tests

**A — one read-only plugin under ENFORCED:**
1. Declare real requirements from the 11-capability vocabulary and register owner-approved grants.
2. Confirm explicit ENFORCED state.
3. Granted read-only operation succeeds.
4. Deliberately undeclared/ungranted operation raises CapabilityDeniedError.
5. Denied operation leaves no side effect.
6. Audit records both granted and denied outcomes with correct plugin/operation.

**B — one plugin under LEGACY_UNDECLARED:**
1. Explicit legacy state.
2. Existing behavior continues.
3. Startup warning identifies plugin and says enforcement is inactive.
4. Warning provides a concrete migration action.
5. Plugin is not silently promoted to ENFORCED or granted unrestricted access due to policy error.

**Phase 4 acceptance boundary:** vocabulary + grant store + service-boundary checks + audit + one read-only ENFORCED migration + one verified LEGACY_UNDECLARED migration path. Adoption of all other plugin tiers is a later phase.

## 10. Non-goals and risks

### 10.1 Non-goals

No process isolation/sandbox, per-plugin subprocess, IPC, arbitrary-import blocking, rewrite of 56 plugins, broad tier adoption, owner-facing .plugin commands, capabilities without confirmed boundaries, Phase 3b/3c redesign, Phase 5 SDK/DX, or RAG.

### 10.2 Risks and mitigations

| Risk | Mitigation |
|---|---|
| False sense of security | Repeat governance-not-sandbox constraint; retain honesty test |
| Legacy mode becomes permanent | Explicit state, actionable warnings, migration reporting |
| Capability implies nonexistent protection | Ship only 11 confirmed service-boundary capabilities |
| Granularity is wrong | Begin domain-level; split only with evidence |
| Service boundary is bypassed | Scoped handle plus authoritative service checks |
| Existing plugins break | Explicit legacy compatibility and two proven paths |
| Grant/cache inconsistency | Existing storage migrations; in-memory cache with immediate revocation invalidation |
| Framework operations are denied | Define and test trusted-core identity before Step 1 ships |
| Plugin callback inherits core authority | Explicitly distinguish core-owned code from plugin-owned callbacks |
| Phase 3b/3c regressions | Preserve semantics and run integration tests |
| Audit noise/data leakage | Aggregate repeated denials; exclude secrets/payloads |
| Rollback implies unrestricted access | Explicit, visible, audited disabled-enforcement state |

## Implementation sequence — authorized after this document commit

Tests-first. Stop and report after each step.

**Step 1 — enforcement core; no plugin migrated and no plugin behavior changed**
- Implement the 11-capability constants and validation.
- Add grant store via additive core/services/storage.py migration/access layer; no new DB file or parallel persistence.
- Implement effective-grant resolution, per-plugin in-memory cache, and explicit invalidation.
- Define trusted-core identity and prove existing framework paths run under it.
- Implement (plugin, capability, operation) check helper raising CapabilityDeniedError or allowing the operation.
- Implement structured audit records for granted/denied outcomes.
- Do not yet enforce at a real service boundary in a way that changes plugin behavior.
- Tests: vocabulary validation; persistent/idempotent/additive grant migration and cache invalidation; declared ∩ approved; trusted-core command registry/job worker/background task; fake plugin denied by helper with no side effect; audit fields/no secrets; isolation honesty test.
- Run local full pytest and compileall; report full summary.

**Step 2 — one read-only plugin**
- Inspect actual .ping or .help service calls before selecting.
- Declare real capabilities and register owner-approved grants.
- Enforce at the relevant service boundary for that plugin's calls only.
- Prove acceptance test A; run locally and report.

**Step 3 — legacy path**
- Select a stable non-migrated plugin.
- Prove acceptance test B under LEGACY_UNDECLARED.
- Run locally and report.

Then stop and report Phase 4 acceptance. Do not reopen Phase 3b/3c, rewrite plugins, add owner-facing commands, add capabilities beyond the 11, or change setup(client)/existing command metadata.

## Source verification note

The existing paths and behaviors described as source-verified were inspected in core/plugins/manager.py, core/context.py, core/registry.py, core/sdk.py, and core/plugins/contract.py. The grant store, capability enforcement, trusted-core identity, and audit stream are design requirements until implemented and tested.
