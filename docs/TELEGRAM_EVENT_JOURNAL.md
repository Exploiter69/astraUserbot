# Telegram Event Journal

## Scope

`TelegramEventJournal` is the C2 durable boundary between normalized Telegram events and downstream projections.

C1 emits bounded `TelegramEvent` envelopes. C2 persists those envelopes in SQLite without retaining raw Telethon objects.

## Guarantees

- SQLite/WAL remains the durable authority.
- Event payloads are JSON and bounded by the C1 collector.
- A deterministic SHA-256 fingerprint provides the idempotency boundary.
- Processing state is explicit: `PENDING`, `PROCESSING`, `PROCESSED`, `FAILED`.
- Failed events retain bounded error text and can be retried.
- Pending work can be enumerated with a bounded limit.
- Journal growth is capped by `MAX_EVENTS` with oldest-first pruning.
- Event rows survive process restart because they live in the platform database.

## Deliberate boundary

The journal is not a projection engine and is not a second job system. C3 owns rebuildable projections; C4 owns replay. JobEngine remains the authority for restart-sensitive execution workflows.

## Retention

The default journal bound is 100,000 rows. Pruning occurs in bounded batches and removes the oldest journal rows first.

The C2 implementation currently bootstraps its table/index schema with `CREATE TABLE IF NOT EXISTS` through the canonical `StorageService`. Future schema changes must preserve deterministic startup and should be promoted to numbered Storage migrations when the journal schema becomes externally depended upon.
