# Telegram Event Replay

`TelegramEventReplay` rebuilds the Telegram event projections from the durable event journal.

## Contract

- Replay is projection-only; it does not mutate the event journal processing state.
- A replay run has a durable run ID, cursor, processed count and state.
- Events are consumed in journal insertion order.
- Batch size is bounded to 500 events.
- Each applied event advances the durable cursor, so interruption can resume without restarting from zero.
- `asyncio.CancelledError` leaves the run `PAUSED` and preserves the last committed cursor.
- A subsequent process can call `resume()` using the same run ID.
- Projection application is idempotent for timeline/entity observations and deterministic for latest-message state.

## States

`RUNNING → PAUSED → RUNNING → COMPLETED`

Unexpected replay errors transition a run to `FAILED` with a bounded error message.

## Scope

The current implementation supports the Telegram projection set only:

- latest message state;
- entity observations;
- Telegram timeline.

New projection types should be added deliberately rather than making replay an unbounded generic executor.

## Storage

The replay run table is currently bootstrapped by the replay service with `CREATE TABLE IF NOT EXISTS`. A future storage migration should absorb this table before this contract is considered final production acceptance.
