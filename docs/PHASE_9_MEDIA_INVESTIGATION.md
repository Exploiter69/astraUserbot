# Phase 9 — Media + Investigation Architecture

**Status:** IMPLEMENTATION COMPLETE / OWNER-HOST ACCEPTANCE PENDING  
**Gates:** `MEDIAINTEL-1`, `MEDIAINTEL-2`, `MEDIAINTEL-3`, `MEDIAINTEL-4`, `CASE-1`, `CASE-2`, `CASE-3`

## Scope

Phase 9 turns authorized media and existing IntelGraph evidence into durable, bounded investigation material. It reuses the existing `MediaService`, `IsolationService`, `AIService`, `IntelGraph`, SQLite and plugin lifecycle instead of introducing another media pipeline or database.

## Prerequisite chain

1. Phase 7 IntelGraph/IOC foundation must remain closed.
2. Phase 8 public intelligence sources must remain closed.
3. Existing MediaService limits and workspace validation remain the media boundary.
4. Existing isolation must be available for FFmpeg/Tesseract analysis where those executables are present.
5. Existing AIService is optional for speech transcription; provider availability is never treated as intelligence failure.
6. Existing SQLite/WAL storage remains the sole durable store.
7. Case data is durable before Phase 9 can be accepted.
8. Automated tests, full regression, compileall and production acceptance must pass before live smoke.
9. Live smoke must use authorized media and non-sensitive test material.

## MEDIAINTEL-1 — content-addressed media observations

`MediaIntelService` computes SHA-256 over the managed media artifact, records a `MEDIA` entity and a `HASH` entity, and links them with an observed `SHARES_HASH` relationship. Size, MIME classification and source filename are retained as bounded provenance metadata.

The service never stores unlimited media bytes in IntelGraph and never treats a hash as an identity claim.

## MEDIAINTEL-2 — perceptual clustering

A deterministic 8x8 grayscale average hash is generated through isolated FFmpeg execution when FFmpeg is available. Candidates are compared with bounded Hamming distance and a fixed threshold. The `mediasim` surface is intentionally a bounded candidate view rather than an assertion that two files depict the same subject.

## MEDIAINTEL-3 — screenshot intelligence

For video, one bounded first frame is extracted through isolated FFmpeg execution. Images and extracted frames can be passed through isolated Tesseract OCR when installed. OCR text is bounded before it is represented as a content-addressed `TEXT` entity and linked to the source media with derived evidence.

## MEDIAINTEL-4 — audio/video intelligence fusion

Audio files and video audio tracks are normalized into bounded mono 16 kHz WAV artifacts through isolated FFmpeg execution. When the existing AIService exposes transcription, the bounded transcript is recorded as a `TEXT` entity linked to the source media. Provider failures produce an explicit unavailable result and do not create false observations.

## CASE-1 — case schema

The durable case model contains:

- case ID;
- title;
- status (`OPEN`/`CLOSED`);
- bounded summary;
- created/updated/closed timestamps;
- attached IntelGraph entities with roles and notes;
- timeline events with event time, kind, description, entity and observation references.

## CASE-2 — case graph/timeline

Case entities are exact IntelGraph references. Case timeline entries preserve event ordering and may point to IntelGraph entities and observations. Timeline reads are bounded and deterministic. `.case graph <case-id>` performs bounded one-hop reads through IntelGraph rather than duplicating graph storage.

## CASE-3 — report generation

Reports are deterministic local renderings of the durable case record, attached entities and timeline. No LLM is required to generate a report and no model output is treated as evidence.

## Resource and safety bounds

- Media input remains subject to existing MediaService size, duration, workspace and disk guards.
- OCR output is capped at 64 KiB.
- Extracted video frame is capped at 2 MiB.
- Perceptual candidate reads are capped at 100 stored pHash rows and 25 returned matches.
- Case reads are capped at 200 rows.
- Case graph output is capped at 25 attached entities and 8 neighbors per entity.
- Reports are capped at 16,000 characters.
- FFmpeg/Tesseract execution is isolated.
- No shell interpretation is introduced.
- No credential access, private-data acquisition, secret extraction, active network scanning or identity attribution is introduced.
- No second database, distributed worker system or paid provider is introduced.

## Command surface

- `.mediaintel` — reply to media for bounded analysis.
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

Interactive command output remains deterministic and compatible with ordinary text commands.
