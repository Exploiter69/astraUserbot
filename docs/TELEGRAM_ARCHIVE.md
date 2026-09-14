# Telegram Archive Job Contract

`ARCH-1` defines the durable contract for bounded Telegram archival.

## Scope

The archive request is represented as a validated JobEngine payload before a worker is introduced.

Fields:

- `peer`
- bounded `limit` (1–500)
- `min_message_id` cursor
- `include_media`
- `schema_version`

The request produces a deterministic idempotency key so repeated submissions of the same archive scope do not create duplicate durable jobs.

## Deliberate boundary

`ARCH-1` does **not** fetch Telegram history, download media, or register a JobEngine worker. Those belong to the archive execution gates.

When execution is added, it must use `TelegramFacade`/`TelegramTrafficController`, JobEngine leases/recovery, bounded batches, cancellation, deduplication, Search/FTS5 and the existing media workspace rather than creating a second workflow or transport path.
