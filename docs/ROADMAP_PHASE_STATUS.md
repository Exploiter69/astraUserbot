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

**Status:** **COMPLETE**  
**Closed:** 2026-09-18  
**Gates:** `MEDIAINTEL-1`, `MEDIAINTEL-2`, `MEDIAINTEL-3`, `MEDIAINTEL-4`, `CASE-1`, `CASE-2`, `CASE-3`  
**Architecture record:** `docs/PHASE_9_MEDIA_INVESTIGATION.md`  
**Acceptance record:** `docs/PHASE_9_ACCEPTANCE.md`

### Completion evidence

- N1 SHA-256 content addressing and authoritative byte-identity evidence;
- N2 pHash, dHash, aHash and bounded perceptual similarity;
- N3 bounded video frame sampling, isolated OCR and deterministic IOC extraction from OCR text;
- N4 bounded audio extraction, optional transcription and deterministic IOC extraction from transcript text;
- O1 durable timeline/event evidence with source/time/confidence support;
- O2 durable case tables, exact IntelGraph references and open/closed lifecycle;
- O3 deterministic evidence reports with observation/entity/source/note/timeline separation;
- Phase 9 static audit: **PASS**;
- focused Phase 9 suite: **52 passed**;
- full regression: **341 passed**;
- compileall: **PASS**;
- production acceptance: **10/10 automated gates PASS**;
- owner-host `astra.service` restart: **PASS**;
- live image OCR smoke: **PASS**;
- live audio transcription smoke: **PASS**;
- live video perceptual fingerprint smoke: **PASS** for two test videos;
- live `.mediasim` exact candidate matches: **PASS**;
- live case lifecycle smoke: **PASS**, including report and final persisted CLOSED state.

### Live case record

Smoke case ID: `dacd9364cb7144f8b291b8ccfe795164`.

The case attached exact PHASH entity `3a17056f437b4547`, recorded a NOTE event, exposed graph/timeline/report views, and was closed successfully. The report exposed confidence `0.95`, source `media-intel-local`, and timestamped evidence.

### Downstream unlock

**Phase 9 is closed. Phase 10 is unlocked.**

Phase 10 work must continue through the roadmap prerequisite → discovery/design → implementation → verification → production acceptance → restart/live smoke → documentation gate sequence.
