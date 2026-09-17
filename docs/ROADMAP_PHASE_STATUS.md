# Roadmap Phase Status

This file records formal gate closures without deleting or rewriting the detailed implementation roadmap in `ROADMAP.md`.

## Phase 7 — Intelligence Foundation

**Status:** COMPLETE  
**Closed:** 2026-09-17  
**Programs:** H IntelGraph foundation; I IOC Engine foundation  
**Acceptance record:** `docs/PHASE_7_ACCEPTANCE.md`

### Completion evidence

- INTEL-1 through INTEL-5 implemented and checked.
- H2 `.intel graph <target>` implemented with exact target resolution, bounded one-hop traversal, pagination and explicit ambiguity handling.
- H3 evidence/correlation boundaries implemented; no unsupported identity assertions.
- Focused IntelGraph/IOC tests: **16 passed**.
- Full regression: **323 passed**.
- Python compilation: **PASS**.
- Production acceptance: **10/10 automated gates PASS**.
- Isolation/security hardening: **PASS**, including malicious-media containment.
- Actual system-level `astra.service` restart: **PASS**.
- Telegram client connected and authorized; runtime healthy with 52 plugins, 138 commands, 22/22 services and Jobs READY.
- Live `.intel graph phase7-smoke-example.invalid`: **PASS**.
- Live `.intel timeline phase7-smoke-example.invalid`: **PASS**.

### Live smoke target

The owner-host smoke used the reserved `.invalid` domain `phase7-smoke-example.invalid` because the production IntelGraph store had no pre-existing entities at the beginning of acceptance. The target is synthetic test data and does not represent a real external domain.

The graph response showed `Edges: 0`, correctly reflecting that no relationship was seeded. The timeline returned an `OBSERVED` observation with confidence `1.00`, confirming persisted evidence was reachable through Telegram.

### Downstream unlock

Phase 7 is closed. Later source-specific intelligence programs may proceed only through their own roadmap gates and must preserve the established provenance, evidence, authorization, bounded-resource, safety and ₹0/$0 constraints.

## Phase 8 — Intelligence Sources

**Status:** COMPLETE  
**Closed:** 2026-09-17  
**Gates:** `TGINTEL-1`, `USER-1`, `DOMAIN-1`, `DOMAIN-2`, `LINK-1`, `GIT-1`  
**Architecture record:** `docs/PHASE_8_INTELLIGENCE_SOURCES.md`  
**Acceptance record:** `docs/PHASE_8_ACCEPTANCE.md`

### Completion evidence

- bounded public Telegram intelligence;
- public username pivots;
- domain DNS/RDAP/HTTP/TLS observations;
- Certificate Transparency collection;
- bounded redirect/link graph;
- public GitHub/GitLab code-profile observations;
- shared HttpService + IntelGraph integration;
- provenance/evidence/confidence boundaries;
- full regression: **328 passed**;
- compileall: **PASS**;
- production acceptance: **10/10 automated gates PASS**;
- owner-host system restart: **PASS**;
- all six live Phase 8 commands: **PASS**.

## Phase 9 — Media + Investigation

**Status:** IMPLEMENTATION COMPLETE / ACCEPTANCE PENDING  
**Gates:** `MEDIAINTEL-1`, `MEDIAINTEL-2`, `MEDIAINTEL-3`, `MEDIAINTEL-4`, `CASE-1`, `CASE-2`, `CASE-3`  
**Architecture record:** `docs/PHASE_9_MEDIA_INVESTIGATION.md`  
**Acceptance record:** `docs/PHASE_9_ACCEPTANCE.md`

### Implementation currently present

- SHA-256 content-addressed media observations;
- deterministic bounded perceptual-hash candidate matching;
- isolated video frame extraction;
- isolated Tesseract screenshot/image OCR where installed;
- bounded audio extraction and optional AIService transcription;
- durable SQLite investigation cases;
- exact IntelGraph entity attachments;
- durable case timelines and observation references;
- deterministic bounded case reports;
- `.mediaintel`, `.mediasim` and `.case` command surfaces;
- shared MediaService/IsolationService/AIService/IntelGraph integration;
- Phase 9 unit and static gate coverage.

### Acceptance status

Implementation is complete, but Phase 9 remains open until owner-host focused tests, full regression, production acceptance, system restart and live media/case smoke are recorded in `docs/PHASE_9_ACCEPTANCE.md`.
