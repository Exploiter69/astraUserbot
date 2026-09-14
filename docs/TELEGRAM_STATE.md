# Telegram State Cache

## Scope

This document records the implementation contract for the `TG-5` entity/dialog cache and the `TG-6` capability-observation gate in Program B (Telegram State Engine).

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

### Implemented by TG-6

- `TelegramFacade.get_capabilities()` for bounded peer capability observations;
- observed `can_read`, `can_send`, `can_edit`, `can_delete`, `can_pin`, `can_react`, slow-mode and restriction state where Telegram exposes it;
- permission discovery through the existing `TelegramTrafficController` rather than a side-channel transport;
- fresh observations persisted through the existing entity cache;
- stale observations trigger a new Telegram observation instead of being treated as current truth;
- `.tgcap` operator command for a compact human-readable capability view;
- permission lookup failures remain classified as unavailable observations rather than silently becoming `False`;
- capability observations remain advisory and never authorize mutations.

## Authority rule

The cache is an observation layer, not Telegram authority.

A fresh in-memory entity object may satisfy repeated read/resolution requests during the configured TTL. Durable SQLite rows are metadata observations and are never reconstructed into mutation authority. When an entity resolution misses or becomes stale, the facade resolves through the normal Telegram traffic controller.

Capability observations follow the same rule. `can_*` values describe what Telegram reported at observation time. Mutation operations must still perform their own current Telegram authorization checks and remain governed by the normal transport path.

This keeps mutation correctness separate from cache freshness and preserves the `TelegramTrafficController` as the only ordinary Telegram transport path.

## Dialog semantics

`get_dialogs()` records the returned bounded snapshot. A cached snapshot is reused only when its requested limit is covered by the cached snapshot and its TTL has not expired. A larger request or expired snapshot goes back through Telegram.

Durable dialog rows remain available through `TelegramStateCache.cached_dialogs()` for rebuildability and diagnostics. They are not silently presented as a fresh Telegram dialog list.

## Capability semantics

Capability discovery is deliberately conservative:

- successful entity resolution is recorded as `can_read=True` as an observation that the peer was resolvable;
- permission-bearing peers use Telegram's current permission response for send/edit/delete/pin/react observations;
- unavailable permission APIs produce `UNKNOWN` values rather than false denials;
- slow mode and restriction flags are recorded only when directly exposed by the resolved entity;
- every capability set contains an `observed_at` timestamp;
- cache TTL controls freshness; it does not extend Telegram authority.

The `.tgcap` command is informational and explicitly labels the result as observation-only.

## Bounds

Defaults:

- entities: 5,000 rows / live objects;
- dialogs: 2,000 rows / live objects;
- entity TTL: 300 seconds;
- dialog TTL: 120 seconds.

The limits are constructor-configurable for tests and deployment profiles. Durable pruning uses oldest-observation-first deletion.

## Failure behavior

Cache persistence is secondary to Telegram correctness. A successful Telegram entity resolution is returned even if persisting its observation fails. Dialog and capability cache writes are similarly best-effort from the facade path. Permission-discovery failure is retained as an unavailable observation rather than converted into a false capability denial.

## Restart behavior

SQLite state survives process restart. Live Telethon objects intentionally do not. After restart, durable metadata can be inspected/rebuilt, while an actual entity resolution still uses Telegram when a live object is required. Fresh capability discovery likewise goes through Telegram when the stored observation is stale or absent.

## Gate boundary

`TG-6` intentionally does **not** claim:

- durable capability truth;
- mutation authorization from cached capabilities;
- incremental history synchronization;
- gap detection/cursor management;
- full Telegram event projections.

Those remain later State/Event gates in the roadmap.
