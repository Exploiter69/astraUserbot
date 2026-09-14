# Telegram Event Projections

**Gate:** C3 / EVENT-3  
**Status:** implementation pending local acceptance

Telegram events have one durable source: `telegram_event_journal`. Projections are derived state and may be deleted/rebuilt without losing the event history.

## Projections

- `telegram_latest_messages` — latest normalized state for each `(source_peer, message_id)`.
- `telegram_entity_observations` — event observations keyed by durable event ID.
- `telegram_timeline` — bounded chronological event view for peer/entity queries.

## Processing

New collector events are journaled first and then projected through the same `ApplicationContext` service graph. Processing is bounded to a small batch and uses journal states `PENDING → PROCESSING → PROCESSED` with `FAILED` remaining retryable.

A startup journal recovery converts interrupted `PROCESSING` events back to `PENDING`. Projection writes are idempotent and use short SQLite transactions.

## Rebuild

`TelegramEventProjections.rebuild()` clears only derived projection tables and reconstructs them from the durable journal. The journal itself is never treated as derived state.

Projection storage is intentionally bounded and local. No raw Telethon objects are persisted.
