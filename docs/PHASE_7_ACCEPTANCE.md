# Phase 7 — Intelligence Foundation Acceptance

**Roadmap phase:** 7  
**Programs:** H IntelGraph foundation; I IOC Engine foundation; INTEL-1 through INTEL-5  
**Status:** **COMPLETE — owner-host production acceptance closed 2026-09-17**

## Scope

Phase 7 leaves Astra with a trustworthy local intelligence substrate before later source-specific intelligence programs are allowed to depend on it.

### Prerequisites satisfied

- Phase 6 Automation Engine is closed and uses the durable JobEngine.
- SQLite/WAL remains the canonical durable store.
- `INTELLIGENCE_OBSERVED` has a real producer path from `IntelGraph.add_observation()`.
- Source lineage is represented in the existing IntelGraph source model.
- Telegram event/timeline projections remain separate from the intelligence graph and are not replaced.

## Gate checklist

### INTEL-1 / H1 — schema and core model

- [x] `intel_sources`
- [x] `intel_entities`
- [x] `intel_observations`
- [x] `intel_relationships`
- [x] foreign keys and indexes
- [x] deterministic entity identity
- [x] source lineage metadata
- [x] timestamps and provenance

### INTEL-2 / H3 — observation/source/confidence/evidence contract

- [x] explicit evidence states: OBSERVED, DERIVED, CORRELATED, INFERRED, UNKNOWN, CONTRADICTED
- [x] confidence bounded to `[0, 1]`
- [x] source-family consistency checks
- [x] bounded evidence queries
- [x] contradictions remain explicit
- [x] automation sink failures cannot erase persisted evidence

### INTEL-3 — deterministic IOC extraction

- [x] URL
- [x] EMAIL
- [x] DOMAIN
- [x] IP
- [x] USERNAME
- [x] HASH
- [x] CVE
- [x] bounded 64 KiB input
- [x] bounded 256 unique indicators
- [x] deterministic ordering

### INTEL-4 — normalization/deduplication

- [x] canonical domain/email/username forms
- [x] canonical IP forms
- [x] normalized HTTP(S) URLs
- [x] CVE uppercase normalization
- [x] explicit hash algorithm labeling
- [x] per-input duplicate collapse
- [x] graph ingestion creates typed entities plus OBSERVED evidence

### INTEL-5 — timeline primitives

- [x] bounded chronological graph timeline
- [x] observations and relationships merged by durable timestamp
- [x] pagination through the operator surface
- [x] no second workflow/event system

### H2 — graph query surface

- [x] `.intel graph <target>`
- [x] exact target resolution without identity guessing
- [x] ambiguity is returned explicitly
- [x] bounded one-hop traversal
- [x] pagination
- [x] evidence state/confidence visible
- [x] supporting observation IDs retained

### Correlation boundary

- [x] correlation classifier is separate from graph persistence
- [x] observed/derived/correlated/inferred/contradicted/unknown remain distinguishable
- [x] contradiction overrides weaker correlation for diagnostics
- [x] unknown evidence does not become an identity claim
- [x] no automatic identity assertion is generated

## Validation evidence

### Owner-host code validation — PASS

Validated on the owner host after pulling `main`:

- Focused IntelGraph/IOC suite: **16 passed** in **4.16s**.
- Python compilation: **PASS** via `python -m compileall -q core plugins tests`.
- Full regression suite: **323 passed** in **45.45s**.

### Production acceptance — PASS

The complete non-destructive production acceptance gate passed all automated gates:

1. Full pytest: **323 passed** in **45.26s**.
2. Compileall: **PASS**.
3. Plugin behavior audit: **PASS**.
4. Plugin ecosystem audit: **PASS** — 52 active plugins, 4 quarantined legacy plugins, 79 declared command registrations, 10 direct event-handler sites; `plugins.intel` setup/shutdown/command registration verified.
5. Media pipeline hardening: **PASS**.
6. Isolation/security hardening: **PASS**, including malicious-media containment, archive safety, filesystem/network boundaries, environment allowlist, timeout handling and actual isolated execution.
7. Storage/database hardening: **PASS** — phase 4 storage checks, 11 plugin databases, retention and transaction checks.
8. Durable job hardening: **PASS**.
9. Phase 18 production hardening: **PASS**.
10. Shutdown probe: **PASS** — context returned in 2.516s with the documented cancellation-resistant-task diagnostic.

Final automated result: **`PRODUCTION_ACCEPTANCE_PASS`**.

### Production runtime acceptance — PASS

The owner-host production service was restarted through the actual system-level `astra.service` and remained healthy:

- systemd service: **active/running**;
- Telegram client: **connected and authorized**;
- Telegram event collector: **started, handlers=6**;
- Automation Engine: **started**;
- Plugins: **52 RUNNING**;
- Commands: **138**;
- Database: **PASS**;
- Services: **22/22**;
- Jobs: **READY**;
- Isolation: **BUBBLEWRAP-AVAILABLE**;
- AI Gateway: **GROQ READY**;
- overall startup: **SYSTEM READY** / **Startup complete**.

### Live Telegram smoke — PASS

A synthetic reserved-domain target was used because the production IntelGraph store had no pre-existing entities at the start of the live smoke. The target uses `.invalid` and therefore does not represent a real external domain.

Seeded target:

- `DOMAIN` · `phase7-smoke-example.invalid`

Live command 1:

```text
.intel graph phase7-smoke-example.invalid
```

Observed Telegram response:

```text
╭─╴⚡ ASTRA  //  INTELGRAPH
│  ROOT `DOMAIN` · `phase7-smoke-example.invalid`
│  Edges: `0` · Page: `1`
╰─╴intel | graph | evidence-backed
```

This confirms exact target resolution, bounded graph output, and no fabricated relationship when none is present.

Live command 2:

```text
.intel timeline phase7-smoke-example.invalid
```

Observed Telegram response:

```text
╭─╴⚡ ASTRA  //  INTEL TIMELINE
│  OBSERVATION · OBSERVED 1.00 · 1789649887
╰─╴intel | timeline | bounded
```

This confirms that persisted observed evidence is reachable through the Telegram timeline surface with evidence state and confidence visible.

## Acceptance decision

**PHASE 7 — COMPLETE.**

The implementation, regression suite, production hardening gates, systemd runtime restart, Telegram authorization/startup, and live `.intel graph` / `.intel timeline` smoke checks are all green. Phase 7 is formally closed as of **2026-09-17**.

This closure does not imply that downstream intelligence programs are implemented. Later source-specific intelligence work remains gated by the roadmap's prerequisite, provenance, evidence and zero-cost constraints.

## Focused validation command

Run from the local checkout after pulling `main`:

```bash
cd ~/AstraUserbot && \
git pull --ff-only origin main && \
.venv/bin/python -m pytest -q tests/test_intelgraph.py tests/test_intelgraph_phase7.py tests/test_ioc.py && \
.venv/bin/python -m compileall -q core plugins tests tools
```

## Production acceptance command

```bash
cd ~/AstraUserbot && \
.venv/bin/python tools/production_acceptance_gate.py
```

## Explicit non-goals

Phase 7 does not perform paid-provider enrichment, broad scraping, private-data acquisition, active network scanning, credential acquisition, or automatic identity claims. Those are outside the foundation gate and must remain downstream, evidence-first capabilities.
