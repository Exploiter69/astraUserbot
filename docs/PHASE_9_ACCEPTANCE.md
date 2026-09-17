# Phase 9 Acceptance — Media + Investigation

**Status:** IMPLEMENTATION COMPLETE / OWNER-HOST ACCEPTANCE PENDING  
**Phase:** 9 — Media + Investigation  
**Closed:** not yet  
**Roadmap gates:** `MEDIAINTEL-1`, `MEDIAINTEL-2`, `MEDIAINTEL-3`, `MEDIAINTEL-4`, `CASE-1`, `CASE-2`, `CASE-3`

## 1. Prerequisite gate

- [x] Phase 7 IntelGraph/IOC foundation is closed.
- [x] Phase 8 intelligence sources are closed.
- [x] Existing MediaService is the media execution and resource boundary.
- [x] Existing isolation boundary is reused for media decoders/OCR.
- [x] Existing AIService is reused for optional speech transcription.
- [x] Existing SQLite/WAL store remains the sole durable case store.
- [x] No second job/workflow system is introduced.
- [ ] Owner-host focused Phase 9 tests pass.
- [ ] Owner-host full regression passes.
- [ ] Owner-host production acceptance passes.
- [ ] Owner-host system restart remains healthy.
- [ ] Owner-host live media/case smoke passes.

## 2. MEDIAINTEL-1

- [x] SHA-256 content addressing.
- [x] Durable `MEDIA` and `HASH` entities.
- [x] Evidence-backed hash relationship.
- [x] Bounded metadata/provenance.
- [x] No raw media payload persistence in IntelGraph.

## 3. MEDIAINTEL-2

- [x] Deterministic 8x8 average-hash representation.
- [x] Isolated FFmpeg generation.
- [x] Bounded Hamming-distance candidate comparison.
- [x] Explicit threshold.
- [x] No perceptual similarity result is treated as identity proof.

## 4. MEDIAINTEL-3

- [x] Bounded first-frame extraction for video.
- [x] Isolated Tesseract OCR where installed.
- [x] OCR output bounded to 64 KiB.
- [x] OCR represented as content-addressed text evidence.
- [x] No screenshot intelligence requires a paid service.

## 5. MEDIAINTEL-4

- [x] Audio extraction from video through isolated FFmpeg.
- [x] Mono 16 kHz bounded transcription input.
- [x] Existing AIService used when transcription is available.
- [x] Transcript represented as bounded text evidence.
- [x] Provider failure is represented as unavailable rather than a false observation.
- [x] No AI mutation authority.

## 6. CASE-1

- [x] Durable case schema.
- [x] Open/closed lifecycle.
- [x] Bounded summary.
- [x] Durable case/entity association.
- [x] Durable case timeline.
- [x] Timestamps preserved.

## 7. CASE-2

- [x] Exact IntelGraph entity references.
- [x] Bounded entity reads.
- [x] Deterministic timeline ordering.
- [x] Observation references supported.
- [x] Case layer does not duplicate the intelligence graph.

## 8. CASE-3

- [x] Deterministic local report generation.
- [x] Report contains case metadata, attached entities and timeline.
- [x] Report bounded to 16,000 characters.
- [x] No LLM dependency for evidence/report generation.

## 9. Command contract

- [x] `.mediaintel`
- [x] `.mediasim <16-hex-pHash>`
- [x] `.case new <title>`
- [x] `.case list`
- [x] `.case show <case-id>`
- [x] `.case add <case-id> <intel-target>`
- [x] `.case event <case-id> <kind> <description>`
- [x] `.case timeline <case-id>`
- [x] `.case report <case-id>`
- [x] `.case close <case-id>`

## 10. Required owner-host validation

Run after pulling the Phase 9 implementation:

```bash
cd ~/AstraUserbot && \
git pull --ff-only origin main && \
.venv/bin/python tools/phase9_media_investigation_audit.py && \
.venv/bin/python -m pytest -q tests/test_media_intel_phase9.py tests/test_phase9_media_cases_gate.py tests/test_runtime_services.py tests/test_media_service.py tests/test_intelgraph.py tests/test_intelgraph_phase7.py tests/test_ioc.py && \
.venv/bin/python -m compileall -q . && \
.venv/bin/python tools/production_acceptance_gate.py
```

Then perform live smoke with authorized non-sensitive media:

1. Reply to a small test image with `.mediaintel`; verify SHA-256 and, when available, pHash/OCR evidence.
2. Reply to a small test audio file with `.mediaintel`; verify transcription is returned or explicitly reported unavailable without a false observation.
3. Reply to a small test video with `.mediaintel`; verify bounded frame/OCR and audio/transcription paths where local capabilities are available.
4. If a pHash is returned, run `.mediasim <returned-pHash>` and verify bounded candidate output.
5. Create a case with `.case new Phase 9 smoke`.
6. Attach an exact IntelGraph target with `.case add <case-id> <intel-target>`.
7. Add a timeline event with `.case event <case-id> NOTE <description>`.
8. Verify `.case show`, `.case timeline`, and `.case report`.
9. Close it with `.case close <case-id>` and verify the closed status.

Do not use private third-party data as test material.

## 11. Completion rule

Phase 9 must remain **PENDING** until the focused tests, full regression, production acceptance, restart and live media/case smoke are all green. Implementation existence alone is not acceptance evidence.
