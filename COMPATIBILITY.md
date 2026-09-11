# Compatibility and Version Policy

## Runtime

- Python: follow the version declared by the repository environment.
- Telethon remains the Telegram transport contract.
- SQLite is the default durable platform store.
- Plugin API major version: `1`.

## Change policy

### Patch
Bug fixes and compatibility-preserving internal changes. No plugin API contract break.

### Minor
New service capabilities, commands, optional metadata and additive SDK features. Existing behavior remains valid.

### Major
Removal or incompatible change of plugin API, service contract, storage contract or command ownership semantics.

Major changes require a migration note, regression coverage and explicit release checklist review.

## Legacy plugins

Legacy `setup(client)` plugins remain supported by the Plugin Manager compatibility adapter. Provider-specific AI command modules that were intentionally quarantined remain compatibility artifacts and are not active command owners.

## Storage

Storage migrations are numbered and checksum-protected. A changed historical migration is a startup error, not a silent rewrite.

## Command compatibility

The command registry remains the authority. A new plugin must not silently take an existing command or alias.
