# Telegram Archive Engine

`ARCH-1` defines the durable archive job contract; `ARCH-2` implements bounded execution, persistence, search, media handling and owner commands.

## Pipeline

`TelegramFacade → bounded JobEngine worker → SQLite search_documents → SQLite FTS5`

Optional media follows:

`TelegramFacade.download_media → MediaService bounded workspace → SHA-256 content-addressed archive/media`

The archive worker does not call raw Telethon transport directly. Telegram history and media operations remain behind the existing governed facade.

## Scope and bounds

- one durable `TELEGRAM_ARCHIVE` job per active request;
- maximum 500 messages per job;
- maximum 100 messages per Telegram history request;
- history is paged backwards with `max_id`;
- `min_message_id` is an inclusive lower boundary;
- optional media is capped at 50 files per job and 512 MiB total;
- individual media remains subject to the existing MediaService input/workspace/disk limits;
- message text is bounded to 64 KiB;
- stored per-message archive metadata is bounded to 32 KiB;
- archive search is bounded to 50 results;
- binary media is stored outside SQLite as SHA-256 content-addressed files;
- SQLite stores searchable metadata including peer, message ID, timestamps, sender/reply references, job ID and media provenance.

## Durable storage

Archive records use the existing canonical `search_documents` SQLite table with source `archive_message`. This keeps archive metadata inside the platform database and makes it naturally available to the canonical FTS5 index without introducing a second database.

The logical document identity is:

`archive_message:<peer>:<message_id>`

Repeated execution of the same batch therefore performs an idempotent upsert rather than duplicating FTS rows.

## Enqueue and idempotency

The request payload has a deterministic base idempotency key. While that request already has an active job, a repeated command reuses the existing job instead of creating duplicate work.

Once the existing archive job reaches a terminal state (`COMPLETED`, `FAILED`, `CANCELLED` or `UNCERTAIN`), a new command creates a fresh durable job with a run-specific key. The historical terminal job is retained as evidence; it is never silently deleted or reset.

This means repeating `.archive chat 5` after a completed or failed run is a new archive attempt, while repeated commands during an active run remain deduplicated.

## Cursor and recovery

The JobEngine owns lifecycle, leasing, heartbeat, retry and shutdown uncertainty. The archive worker writes an `ARCHIVE_CURSOR` job event only after the preceding batch has been persisted. If a worker disappears before that event, the previous batch is replayed safely because archive records are idempotent.

An active job interrupted by cancellation or shutdown is not reported as cleanly complete. Existing JobEngine semantics mark it `UNCERTAIN`; explicit operator verification/requeue remains required before replaying uncertain work.

## Media

Media is downloaded through `TelegramFacade.download_media`, which classifies the operation as governed `MEDIA` traffic. `MediaService` supplies the bounded workspace, disk guard and Telegram download progress guard.

Completed media is SHA-256 hashed and moved atomically into:

`data/archive/media/<first-two-hash-characters>/<sha256><original-suffix>`

Identical content reuses the existing object. SQLite metadata records the relative path, hash, byte size, MIME type, original name and archive status.

Media failures/limits do not discard the text/message metadata. The record is retained with a bounded media status/error classification.

## Commands

The owner-facing plugin supports:

- `.archive chat [limit]` — archive bounded history from the current chat;
- `.archive channel [limit]` — archive bounded history from the current channel context;
- `.archive since <message_id> [limit]` — archive backward to the supplied message-ID floor;
- `.archive media [limit]` — archive bounded history with optional media capture;
- `.archive search <query>` — search only archived messages through FTS5.

The commands are deterministic and text-first. Interactive pagination/job controls can be added by the later UX program without changing the durable archive contract.

## Takeout sessions

Telegram takeout sessions are intentionally not mandatory for ARCH-2. They remain a future optimization for suitable bulk-export workflows. The normal archive path already uses bounded requests and resumable JobEngine state.

## Failure policy

- invalid job input → permanent `ARCHIVE_INVALID_PAYLOAD`;
- Telegram history failure → bounded JobEngine retry;
- media size/storage/validation issue → retain message metadata and mark media skipped;
- cancellation/shutdown → existing JobEngine uncertainty semantics;
- no unbounded message batches, media buffers or job payloads are introduced.
