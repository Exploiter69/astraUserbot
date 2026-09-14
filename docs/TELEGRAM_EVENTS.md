# Telegram Event Collector

The Telegram Event Collector is the first gate of Program C (Telegram Event Engine).

## Contract

`TelegramEventCollector` observes Telethon updates and converts supported update families into bounded `TelegramEvent` envelopes:

- `MESSAGE_NEW`
- `MESSAGE_EDIT`
- `MESSAGE_DELETE`
- `REACTION_CHANGED`
- `CHAT_MEMBER_CHANGED`
- `CALL_STATE_CHANGED`

The collector is registered as an ApplicationContext service and owns its Telethon handler lifecycle. Shutdown unregisters every handler.

## Boundaries

- Raw Telethon update objects are never passed to event sinks.
- Message text is bounded to 4096 characters.
- Deleted-message batches are bounded to 100 message IDs per update.
- Event payloads are converted to JSON-friendly scalar/list values with bounded string representations.
- Sink failures are isolated so one consumer cannot stop collection.
- The collector has a bounded maximum of 32 sinks.
- Event IDs are locally generated and schema-versioned.

## Durability

This gate establishes normalization and collection only. Durable event persistence, processing state, retention and replay are part of the subsequent C2/C3/C4 gates.

## Compatibility

Existing plugins continue to own their own event handlers. The collector observes the same Telethon client and does not remove or replace plugin handlers.
