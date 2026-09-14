# Telegram State Cache

## Scope

This document records the implementation contract for the `TG-5` entity/dialog cache gate in Program B (Telegram State Engine).

### Implemented by TG-5

- bounded in-memory entity cache for live Telethon objects;
- durable SQLite entity observations;
- entity metadata: ID, access hash, username, title/name, type, last-seen timestamp and photo metadata;
- optional capability observations stored as timestamped cache data, without treating them as permanent authority;
- bounded in-memory dialog cache;
- durable dialog observations with peer, type, title/username, last observed message ID, sync timestamp and sync state;
- entity TTL and dialog TTL;
- explicit invalidation for entities and dialogs;
- single-flight concurrent entity resolution to prevent cache stampedes;
- bounded durable pruning and bounded in-memory eviction;
- rebuildable dialog/entity state from SQLite after process restart;
- TelegramFacade integration for `get_entity` and `get_dialogs`;
- state diagnostics through `TelegramFacade.state_snapshot()`.

## Authority rule

The cache is an observation layer, not Telegram authority.

A fresh in-memory entity object may satisfy repeated read/resolution requests during the configured TTL. Durable SQLite rows are metadata observations and are never reconstructed into mutation authority. When an entity resolution misses or becomes stale, the facade resolves through the normal Telegram traffic controller.

This keeps mutation correctness separate from cache freshness and preserves the `TelegramTrafficController` as the only ordinary Telegram transport path.

## Dialog semantics

`get_dialogs()` records the returned bounded snapshot. A cached snapshot is reused only when its requested limit is covered by the cached snapshot and its TTL has not expired. A larger request or expired snapshot goes back through Telegram.

Durable dialog rows remain available through `TelegramStateCache.cached_dialogs()` for rebuildability and diagnostics. They are not silently presented as a fresh Telegram dialog list.

## Bounds

Defaults:

- entities: 5,000 rows / live objects;
- dialogs: 2,000 rows / live objects;
- entity TTL: 300 seconds;
- dialog TTL: 120 seconds.

The limits are constructor-configurable for tests and deployment profiles. Durable pruning uses oldest-observation-first deletion.

## Failure behavior

Cache persistence is secondary to Telegram correctness. A successful Telegram entity resolution is returned even if persisting its observation fails. Dialog cache writes are similarly best-effort from the facade path. Cache failures therefore do not turn a successful Telegram operation into a user-visible Telegram failure.

## Restart behavior

SQLite state survives process restart. Live Telethon objects intentionally do not. After restart, durable metadata can be inspected/rebuilt, while an actual entity resolution still uses Telegram when a live object is required.

## Gate boundary

`TG-5` intentionally does **not** claim:

- Telegram capability discovery (`TG-6`);
- durable capability truth;
- incremental history synchronization;
- gap detection/cursor management;
- full Telegram event projections.

Those remain later State/Event gates in the roadmap.
