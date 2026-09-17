# Phase 7 — Intelligence Foundation Acceptance

**Roadmap phase:** 7  
**Programs:** H IntelGraph foundation; INTEL-1 through INTEL-5  
**Status:** implementation complete; owner-host production acceptance pending

## Scope

Phase 7 must leave Astra with a trustworthy local intelligence substrate before later source-specific intelligence programs are allowed to depend on it.

### Prerequisites satisfied

- Phase 6 Automation Engine is closed and uses the durable JobEngine.
- SQLite/WAL remains the canonical durable store.
- `INTELLIGENCE_OBSERVED` already has a real producer path from `IntelGraph.add_observation()`.
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

Validated on the owner host after pulling the latest `main`:

- Focused IntelGraph/IOC suite: **16 passed** in **4.16s**.
- Python compilation: **PASS** via `python -m compileall -q core plugins tests tools`.
- Full regression suite: **323 passed** in **45.45s**.

These results establish that the Phase 7 implementation is regression-clean. They do **not** by themselves close the production acceptance gate.

## Focused validation command

Run from the local checkout after pulling `main`:

```bash
cd ~/AstraUserbot && \
git pull --ff-only origin main && \
.venv/bin/python -m pytest -q tests/test_intelgraph.py tests/test_intelgraph_phase7.py tests/test_ioc.py && \
.venv/bin/python -m compileall -q core plugins tests tools
```

## Remaining owner-host acceptance

The final phase decision requires the focused tests, full suite, compile check and production acceptance gate to remain green on the owner host. After that, runtime smoke must confirm that the `intel` plugin loads without command collisions and that existing automation/Telegram startup remains healthy.

Run the remaining production gate with:

```bash
cd ~/AstraUserbot && \
.venv/bin/python tools/production_acceptance_gate.py
```

Then perform the runtime smoke/operational checks required by the production acceptance process, including confirmation of the `.intel` command surface alongside the existing automation and Telegram startup health.

**Phase 7 remains open until that production acceptance evidence is recorded.**

## Explicit non-goals

Phase 7 does not perform paid-provider enrichment, broad scraping, private-data acquisition, active network scanning, credential acquisition, or automatic identity claims. Those are outside the foundation gate and must remain downstream, evidence-first capabilities.
