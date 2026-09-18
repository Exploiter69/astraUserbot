# Phase 9 Acceptance — Media + Investigation

**Status:** **COMPLETE — owner-host acceptance closed 2026-09-18**  
**Phase:** 9 — Media + Investigation  
**Closed:** 2026-09-18  
**Roadmap gates:** `MEDIAINTEL-1`, `MEDIAINTEL-2`, `MEDIAINTEL-3`, `MEDIAINTEL-4`, `CASE-1`, `CASE-2`, `CASE-3`

## 1. Prerequisite gate

- [x] Phase 7 IntelGraph/IOC foundation is closed.
- [x] Phase 8 intelligence sources are closed.
- [x] Existing MediaService is the media execution and resource boundary.
- [x] Existing isolation boundary is reused for media decoders/OCR.
- [x] Existing AIService is reused for optional speech transcription.
- [x] Existing SQLite/WAL store remains the sole durable case store.
- [x] No second job/workflow system is introduced.
- [x] Owner-host focused Phase 9 tests pass after the final implementation correction pass.
- [x] Owner-host full regression passes after the final implementation correction pass.
- [x] Owner-host production acceptance passes after the final implementation correction pass.
- [x] Owner-host system restart remains healthy.
- [x] Owner-host live media/case smoke passes.

## 2. MEDIAINTEL-1

- [x] SHA-256 content addressing.
- [x] Durable `MEDIA` and `HASH` entities.
- [x] Evidence-backed byte-identity relationship.
- [x] Perceptual hashes are stored as separate derived similarity signals.
- [x] Bounded metadata/provenance.
- [x] No raw media payload persistence in IntelGraph.

## 3. MEDIAINTEL-2

- [x] Dependency-free DCT pHash representation.
- [x] Deterministic 8x8 average-hash representation.
- [x] dHash representation.
- [x] Isolated FFmpeg generation.
- [x] Bounded Hamming-distance candidate comparison.
- [x] Explicit threshold.
- [x] No perceptual similarity result is treated as identity proof.

## 4. MEDIAINTEL-3

- [x] Bounded three-frame early video sampling.
- [x] Isolated Tesseract OCR where installed.
- [x] OCR output bounded to 64 KiB.
- [x] OCR represented as content-addressed text evidence.
- [x] OCR text passes through the existing deterministic IntelGraph IOC extraction/normalization pipeline.
- [x] No screenshot intelligence requires a paid service.

## 5. MEDIAINTEL-4

- [x] Audio extraction from video through isolated FFmpeg.
- [x] Mono 16 kHz bounded transcription input.
- [x] Existing AIService used when transcription is available.
- [x] Transcript represented as bounded text evidence.
- [x] Transcript passes through the existing deterministic IntelGraph IOC extraction/normalization pipeline.
- [x] Provider failure is represented as unavailable rather than a false observation.
- [x] No AI mutation authority.

## 6. CASE-1

- [x] Durable `cases` schema.
- [x] Durable `case_entities` association.
- [x] Durable `case_observations` references.
- [x] Durable `case_notes` records.
- [x] Durable `case_sources` references.
- [x] Durable `case_events` records.
- [x] Compatibility/read-model `case_timeline`.
- [x] Open/closed lifecycle.
- [x] Bounded summary and note text.
- [x] Timestamps preserved.

## 7. CASE-2

- [x] Exact IntelGraph entity references.
- [x] Bounded entity reads.
- [x] Bounded observation/source capture for attached entities.
- [x] Deterministic timeline ordering.
- [x] Observation references supported.
- [x] `.case graph <case-id>` provides bounded one-hop graph reads through IntelGraph.
- [x] Case layer does not duplicate the intelligence graph.

## 8. CASE-3

- [x] Deterministic local report generation.
- [x] Report contains case metadata, attached entities and timeline.
- [x] Report exposes evidence state/confidence and source/time information when available.
- [x] Report separates observations, entities, sources and notes.
- [x] Report bounded to 16,000 characters.
- [x] No LLM dependency for evidence/report generation.

## 9. Command contract

- [x] `.mediaintel` — command-attached or replied media.
- [x] `.mediasim <16-hex-pHash>`
- [x] `.case new <title>`
- [x] `.case list`
- [x] `.case show <case-id>`
- [x] `.case graph <case-id>`
- [x] `.case add <case-id> <intel-target>`
- [x] `.case event <case-id> <kind> <description>`
- [x] `.case timeline <case-id>`
- [x] `.case report <case-id>`
- [x] `.case close <case-id>`

## 10. Owner-host validation evidence

Run after pulling the final Phase 9 implementation:

```bash
cd ~/AstraUserbot && \
git pull --ff-only origin main && \
.venv/bin/python tools/phase9_media_investigation_audit.py && \
.venv/bin/python -m pytest -q tests/test_media_intel_phase9.py tests/test_phase9_media_cases_gate.py tests/test_runtime_services.py tests/test_media_service.py tests/test_intelgraph.py tests/test_intelgraph_phase7.py tests/test_ioc.py && \
.venv/bin/python -m compileall -q . && \
.venv/bin/python tools/production_acceptance_gate.py
```

Then perform live smoke with authorized non-sensitive media:

1. Reply to a small test image with `.mediaintel`; verify SHA-256, pHash/aHash/dHash and OCR when Tesseract is available.
2. Reply to a small test audio file with `.mediaintel`; verify transcription is returned or explicitly reported unavailable without a false observation.
3. Reply to a small test video with `.mediaintel`; verify bounded frame sampling, OCR and audio/transcription paths where local capabilities are available.
4. If a pHash is returned, run `.mediasim <returned-pHash>` and verify bounded candidate output.
5. Create a case with `.case new Phase 9 smoke`.
6. Attach an exact IntelGraph target with `.case add <case-id> <intel-target>`.
7. Add a timeline event with `.case event <case-id> NOTE <description>`.
8. Verify `.case show`, `.case graph`, `.case timeline`, and `.case report`.
9. Close it with `.case close <case-id>` and verify the closed status.

Do not use private third-party data as test material.

## 11. Owner-host validation evidence

The final owner-host validation pass completed before live smoke:

- Phase 9 static audit: **PASS**.
- Focused Phase 9 suite: **52 passed**.
- Full regression suite: **341 passed**.
- Python `compileall`: **PASS**.
- Production acceptance: **10/10 automated gates PASS**.
- Overall result: **`PRODUCTION_ACCEPTANCE_PASS`**.
- `astra.service` restarted successfully and returned healthy with runtime READY, Telegram CONNECTED, database PASS, 25/25 services, 54 running plugins, 147 commands, Jobs READY, Bubblewrap available and AI Gateway READY.

### Live media smoke

Authorized, non-sensitive test media was exercised through the real Telegram command path.

- Image `.mediaintel`: SHA-256, pHash-family fingerprints, one sampled frame and OCR were returned; OCR text was `JAIPUR`.
- Audio `.mediaintel`: SHA-256 and transcript `Thanks for watching!` were returned.
- Two video test files produced pHash/dHash/aHash fingerprints.
- `.mediasim` returned bounded zero-distance matches for both returned pHashes.
- The tested video clips did not surface additional OCR/transcription fields in the Telegram response; no false observation was recorded. Bounded frame/OCR/audio-fusion behavior is covered by the automated Phase 9 gate and implementation contracts.

Video 1 pHash: `3a17056f437b4547`  
Video 2 pHash: `63d898c3ff372620`

### Live case smoke

Smoke case ID: `dacd9364cb7144f8b291b8ccfe795164`.

The real command sequence completed successfully:

`.case new` → `.case add` with exact PHASH target → `.case event` → `.case show` → `.case graph` → `.case timeline` → `.case report` → `.case close` → final `.case show`.

The attached exact IntelGraph entity was PHASH `3a17056f437b4547`, entity ID `b93c788253d88cfc8e2e06a6483d0a847692a7fabed750959c6f0be26eb30c43`. The report exposed confidence `0.95`, source `media-intel-local`, and timestamped evidence. Final persisted case status was **CLOSED**.

## 12. Completion rule

All Phase 9 prerequisites, implementation gates, automated acceptance gates, production restart checks and live Telegram media/case smoke checks are green.
