# Phase 9 — Media + Investigation Architecture

**Status:** **COMPLETE — owner-host acceptance closed 2026-09-18**  
**Gates:** `MEDIAINTEL-1`, `MEDIAINTEL-2`, `MEDIAINTEL-3`, `MEDIAINTEL-4`, `CASE-1`, `CASE-2`, `CASE-3`

## Scope

Phase 9 turns authorized media and existing IntelGraph evidence into durable, bounded investigation material. It reuses the existing `MediaService`, `IsolationService`, `AIService`, `IntelGraph`, SQLite/WAL and plugin lifecycle instead of introducing another media pipeline, database or workflow system.

## Prerequisite chain

1. Phase 7 IntelGraph/IOC foundation remains closed.
2. Phase 8 public intelligence sources remain closed.
3. Existing MediaService limits, Telegram download guards and workspace validation remain the media boundary.
4. Existing isolation is required for FFmpeg/Tesseract analysis where those executables are present.
5. Existing AIService is optional for speech transcription; provider availability is never treated as an intelligence fact.
6. Existing SQLite/WAL storage remains the sole durable store.
7. Case data is durable before Phase 9 can be accepted.
8. Automated tests, full regression, compileall and production acceptance must pass before live smoke.
9. Live smoke must use authorized, non-sensitive test media.

## MEDIAINTEL-1 — content-addressed media observations

`MediaIntelService` computes SHA-256 over the managed media artifact, records a `MEDIA` entity and a `HASH` entity, and links them with observed `SHARES_HASH` evidence. Size, MIME classification and source filename remain bounded provenance metadata. Raw media bytes are not stored in IntelGraph.

SHA-256 is the authoritative byte identity. Perceptual hashes are separate similarity signals and are never used as identity proof.

## MEDIAINTEL-2 — perceptual clustering

The service produces three bounded 64-bit image fingerprints from an isolated FFmpeg frame: DCT pHash, average aHash and dHash. pHash remains the command-facing similarity key for `.mediasim`; aHash/dHash are retained as additional derived media signals. Candidate comparison uses bounded Hamming distance and a fixed threshold.

For video, fingerprinting and analysis are limited to a maximum of three sampled frames at fixed early timestamps. The implementation never performs unbounded frame extraction.

## MEDIAINTEL-3 — screenshot intelligence

Images are analyzed directly and videos use up to three bounded early frames extracted through isolated FFmpeg execution. Isolated Tesseract OCR is used when installed. OCR output is capped at 64 KiB, stored as content-addressed `TEXT` evidence and linked to the source media. OCR text is also passed through the existing deterministic IntelGraph IOC extraction/normalization pipeline so URLs, domains, IPs, emails, usernames and other supported indicators become traceable graph evidence.

## MEDIAINTEL-4 — audio/video intelligence fusion

Audio files and video audio tracks are normalized into bounded mono 16 kHz WAV artifacts through isolated FFmpeg execution. When the existing AIService exposes transcription, the bounded transcript is recorded as a `TEXT` entity and linked to the source media. Transcript text is also passed through the existing deterministic IOC extraction/normalization pipeline. Provider failures produce an explicit unavailable result and never create false observations.

## CASE-1 — case schema

The durable case model contains the roadmap's case concepts:

- `cases` — ID, title, status, summary and lifecycle timestamps;
- `case_entities` — exact IntelGraph entity references with role/note metadata;
- `case_observations` — durable observation references;
- `case_notes` — bounded local notes;
- `case_sources` — durable source references;
- `case_events` — durable event records;
- `case_timeline` — compatibility/read model containing event time, kind, description, entity and observation references.

All case data remains in the canonical SQLite/WAL store.

## CASE-2 — case graph/timeline

Case entities are exact IntelGraph references. Attaching an entity captures bounded linked observations and their source IDs. Timeline entries preserve deterministic ordering and may point to entities and observations. `.case graph <case-id>` performs bounded one-hop reads through IntelGraph rather than duplicating graph storage.

## CASE-3 — report generation

Reports are deterministic local renderings and do not depend on an LLM. They separate the available evidence into observation state/confidence, attached entities, sources, notes and timeline entries. Unknown or unavailable information is not fabricated, and the report is capped at 16,000 characters.

## Owner-host acceptance evidence

- Phase 9 static audit: **PASS**.
- Focused Phase 9 suite: **52 passed**.
- Full regression: **341 passed**.
- `compileall`: **PASS**.
- Production acceptance: **10/10 automated gates PASS**.
- `astra.service` restart: **PASS** and healthy.
- Live image OCR and audio transcription smoke: **PASS**.
- Live video perceptual fingerprint smoke: **PASS** for two test videos.
- Live `.mediasim`: **PASS**, including zero-distance matches.
- Live case lifecycle: **PASS**, including exact IntelGraph attachment, report generation, close, and final CLOSED persistence.

Smoke case: `dacd9364cb7144f8b291b8ccfe795164`; attached PHASH target: `3a17056f437b4547`.



- Media input remains subject to existing MediaService size, duration, workspace and disk guards.
- OCR/transcript text is capped at 64 KiB.
- Extracted video frames are capped at 2 MiB each.
- Video analysis samples at most 3 fixed early frames.
- Perceptual candidate reads are capped at 100 stored pHash rows and 25 returned matches.
- Case reads are capped at 200 rows.
- Case observation/source reads are bounded.
- Case graph output is capped at 25 attached entities and 8 neighbors per entity.
- Reports are capped at 16,000 characters.
- FFmpeg/Tesseract execution is isolated through the existing isolation boundary.
- No shell interpretation is introduced.
- No credential access, private-data acquisition, secret extraction, active network scanning or identity attribution is introduced.
- No second database, distributed worker system or paid provider is introduced.

## Command surface

- `.mediaintel` — analyze media attached to the command or media in the replied-to message.
- `.mediasim <16-hex-pHash>` — bounded perceptual candidates.
- `.case new <title>`
- `.case list`
- `.case show <case-id>`
- `.case graph <case-id>`
- `.case add <case-id> <intel-target>`
- `.case event <case-id> <kind> <description>`
- `.case timeline <case-id>`
- `.case report <case-id>`
- `.case close <case-id>`

The `.mediaintel` resolver intentionally does not depend solely on Telethon's `is_reply` convenience property: it attempts direct reply resolution and also supports media attached to the command message itself.

Interactive command output remains deterministic and compatible with ordinary text commands.
