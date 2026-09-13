# AstraUserbot — Whole-System Audit

**Date:** 2026-09-13  
**Scope:** platform architecture, plugin boundaries, persistence, jobs, AI, isolation, lifecycle, production configuration, dependency posture and remaining operational risks  
**Cost target:** ₹0 / $0

## Executive result

The platform hardening program is substantially complete. Owner-host evidence currently shows:

- 182 tests passed;
- isolation/security audit passed;
- storage/database audit passed;
- durable-job audit passed;
- Phase 18 production audit passed;
- the real systemd shutdown gate previously completed successfully;
- four legacy AI modules remain quarantined by design.

No new P0/P1 platform defect was identified during this review.

## Findings and disposition

### F1 — Autopost peer identity was not durable enough — FIXED

The scheduler persisted only a numeric `chat_id`. For users and channels, Telethon may require an access hash after restart; this produced the observed `PeerUser` resolution failure.

The plugin now persists peer type plus access hash for new schedules and reconstructs `InputPeerUser` / `InputPeerChannel` / `InputPeerChat` targets during worker execution. Regression coverage was added for user and channel peer reconstruction and worker dispatch.

Existing rows created before this migration remain compatibility rows with `peer_type='id'`; they should be recreated if Telethon can no longer resolve them from its entity cache.

### F2 — Isolation documentation was stale — FIXED

The old readiness text described isolation as deferred even though the real Bubblewrap boundary had been implemented and owner-host validated.

`PHASE_10_15_READINESS.md` now records Phase 14 as real selective isolation, and ADR-029 is explicitly superseded by ADR-032.

### F3 — Ordinary plugins remain same-process trust — ACCEPTED

The plugin manager provides lifecycle and ownership isolation, not memory/security isolation. This is intentional. Only classified child workloads cross the Bubblewrap boundary.

### F4 — Network-requiring subprocesses are not isolated — ACCEPTED

Downloads, rclone and network TTS require network access and therefore remain outside the network-disabled isolation profile. They continue to use bounded shared subprocess/media policies. They must not be described as sandboxed.

### F5 — AI provider-specific legacy modules remain quarantined — ACCEPTED

`plugins.ai.ask`, `plugins.ai.groq_client`, `plugins.ai.summarize`, and `plugins.ai.transcribe` are compatibility artifacts only. Active AI behavior uses the provider-independent gateway.

### F6 — Runtime shutdown audit still requires live proof — ACCEPTED

The static Phase 18 audit deliberately reports `SHUTDOWN_RUNTIME_GATE_REQUIRED: YES`. The live owner-host gate has already demonstrated clean systemd shutdown with no timeout/kill failure. The warning about a cancellation-resistant worker is expected from the deliberately hostile shutdown probe and does not block shutdown completion.

### F7 — Dependency posture — PASS

The pinned direct dependencies are current at the reviewed versions. In particular, `cryptography==50.0.1` and `aiohttp==3.14.3` are current secure releases as of this review; `aiosqlite==0.22.1` has no known direct vulnerabilities in the reviewed database, and Telethon 1.44.0 has no direct vulnerability listed in the reviewed source. Dependency status should still be rechecked before future releases.

## Remaining non-blocking risks

1. There is no mandatory hosted CI requirement; owner-host verification remains the authoritative runtime gate for this local userbot.
2. The authorization/capability model is intentionally centered on the outgoing self-command boundary and direct security watchers; it should not be advertised as a generic multi-user ACL framework.
3. Legacy plugin databases remain separate by design; consolidation is not required for correctness.
4. Production credentials remain process environment state. Child isolation clears inherited environment variables, but host-level process permissions still matter.
5. Backup verification remains an operational responsibility before destructive production maintenance.

## Next engineering priority

Do **not** start another platform rewrite. The next phase should be **operational maturity and feature migration**, driven by actual plugin behavior:

1. run the post-audit regression after the autopost migration;
2. reconcile the canonical roadmap/readiness documents with the now-completed phases;
3. identify the highest-value remaining plugin behavior defects from production telemetry;
4. only then expand features.

The architecture should remain a single-process, local-first modular monolith with SQLite durability and explicit process isolation only where justified by workload.
