# ARCH-2 Acceptance Record

## Scope

`ARCH-2` — bounded history/media archive, following the Phase 3 roadmap dependency after `ARCH-1`.

## Dependency check

- `ARCH-1` request model exists and remains the durable enqueue contract.
- Telegram history access uses `TelegramFacade.get_messages()` and therefore the existing `TelegramTrafficController`.
- Telegram media access uses `TelegramFacade.download_media()` and governed `MEDIA` traffic.
- `JobEngine` owns durable lifecycle, leasing, retry, progress, cancellation and uncertainty/recovery.
- `SearchService`/SQLite FTS5 is reused rather than introducing another index.
- `MediaService`/`WorkspaceService` is reused for bounded temporary media work.
- No new database or distributed worker system is introduced.

## Implementation checklist

- [x] bounded history retrieval
- [x] backward pagination using `max_id`
- [x] inclusive `min_message_id` floor
- [x] maximum 500 messages per job
- [x] maximum 100 Telegram messages per fetch
- [x] durable cursor in JobEngine `job_events`
- [x] restart-safe archived-count recovery
- [x] idempotent SQLite archive records
- [x] FTS5 archive-only search
- [x] optional media capture
- [x] 50 media-file/job bound
- [x] 512 MiB media/job bound
- [x] MediaService size/disk/workspace guards
- [x] SHA-256 content-addressed media
- [x] atomic media placement
- [x] cancellation propagation
- [x] retry classification for Telegram fetch failures
- [x] owner-only command registration
- [x] deterministic text command surface
- [x] durable progress through JobEngine
- [x] documentation
- [x] focused tests for pagination, resume, search, failure classification and media addressing

## Command surface

- `.archive chat [limit]`
- `.archive channel [limit]`
- `.archive since <message_id> [limit]`
- `.archive media [limit]`
- `.archive search <query>`

## Explicit non-goals

- Takeout is not a mandatory dependency; it remains an optional future bulk-export optimization.
- Interactive progress/pagination/cancel UI belongs to `UX-2`.
- No raw Telegram object payloads are persisted.
- No second job engine, message transport or search index is introduced.

## Validation status

### Automated owner-host validation

- Focused archive/runtime tests: **PASS** — 17 passed.
- Complete existing test suite: **PASS** — 269 passed.
- Phase 16 runtime-service lifecycle expectation updated to include `telegram_archive`.

### Remaining production acceptance

The ARCH-2 production acceptance gate remains pending the owner-host runtime smoke with the real Telegram session. The smoke must exercise the actual `enqueue()` → `JobEngine` path and verify, using a small bounded archive scope:

1. owner-only command authorization;
2. successful `.archive chat <small-limit>` execution;
3. durable job creation/completion and progress;
4. durable archive records and archive-only FTS search;
5. governed Telegram history traffic through `TelegramFacade`/`TelegramTrafficController`;
6. restart/recovery behavior for an interrupted archive job;
7. media archival only when explicitly requested and within the documented bounds.

ARCH-2 is **test-green but not production-accepted** until this runtime smoke is completed and recorded.
