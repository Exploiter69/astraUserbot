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

Implementation is on GitHub. The owner-host acceptance gate remains pending until the local repository runs the focused archive tests and the complete existing suite, followed by the normal clean-tree/commit verification procedure.
