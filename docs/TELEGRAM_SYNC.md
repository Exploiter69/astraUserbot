# Telegram Incremental Synchronization

This document records the Program B4 state-engine contract.

## Contract

Astra keeps synchronization cursors in the existing `telegram_dialogs` table:

- peer key;
- last observed message ID;
- last synchronization timestamp;
- synchronization state.

The synchronization service is deliberately bounded by a configurable maximum
batch size and uses the existing `TelegramFacade` transport path, so Telegram
traffic remains governed by `TelegramTrafficController`.

## Recovery

A synchronization run marks its cursor `RUNNING` before transport work starts.
A failed run becomes `FAILED`. A later run resumes from the durable message
cursor and records `GAP_DETECTED` when the previous run was interrupted or
failed. The gap flag is retained as an observation until a future recovery gate
provides an explicit verification/repair policy.

This makes restart state observable without pretending that a partial sync was
complete.

## Bounds

- Default/max implementation batch: 100 messages per invocation.
- No complete-history scan is implicit.
- Cursor writes are durable through `StorageService`.
- Telegram requests continue through the central traffic controller.
- The sync layer does not grant mutation authority from cached state.

## Operator surface

`.tgsync [peer] [limit]` performs one bounded synchronization step and reports
the cursor, fetched count, state and gap observation.

## Gate boundary

This gate establishes resumable bounded synchronization and durable cursors.
It does not claim a complete event projection, archive pipeline, or replay
engine; those remain later roadmap programs.
