# AstraUserbot — Storage / Database Hardening

**Status:** COMPLETE
**Scope:** canonical platform SQLite plus independent legacy plugin SQLite stores
**Cost:** ₹0 / $0

## Contract

SQLite remains the durable source of truth for Astra operational state. The canonical platform database and independent plugin databases use bounded local SQLite adapters rather than external database infrastructure.

### Migrations

- platform migrations are numbered and checksummed;
- each migration runs under `BEGIN IMMEDIATE` so concurrent openers cannot apply the same migration twice;
- failed migrations roll back and startup fails closed;
- checksum drift is rejected;
- migration replay is idempotent.

### Transactions and concurrency

- normal writes are serialized through an asyncio lock per database connection;
- multi-statement writes use explicit transactions with rollback on failure;
- SQLite WAL is enabled;
- foreign keys are enabled;
- busy timeout is bounded at 5 seconds;
- no transaction may intentionally span external Telegram/HTTP/process/AI work.

### Integrity and corruption

- startup performs `PRAGMA integrity_check`;
- foreign-key violations are rejected;
- SQLite errors are converted into bounded storage-layer exceptions;
- corrupted databases fail startup instead of being silently accepted;
- recovery is performed from an integrity-verified backup.

### WAL maintenance

The storage services expose bounded checkpoint operations. The database-size measurement includes the database plus WAL/SHM sidecars so operators do not mistake the main `.db` file for the complete SQLite footprint.

### Backup / restore

Backups use SQLite's online backup API rather than copying a live database file. A backup is integrity-checked before publication and atomically renamed into place. Restore accepts only an integrity-verified SQLite backup and is permitted only while the target service is stopped; stale WAL/SHM sidecars are removed after replacement.

### Search / FTS5

FTS5 is derived state. Source records remain authoritative. Search upserts update the source and FTS row in one transaction. The storage layer can detect orphan/missing FTS rows, and the search service can rebuild the index from source records.

### Retention and size

Durable job retention remains governed by the JobEngine and never silently removes `UNCERTAIN` jobs. Database footprint is observable and backup/restore operations have a 2 GiB safety bound. Other plugin data keeps its feature-specific retention policy rather than receiving an unsafe universal delete policy.

### Plugin-specific databases

Independent plugin databases are intentionally retained during the incremental migration. The hardened compatibility adapter provides WAL, foreign keys, bounded contention, transactions, integrity checks, verified backups, size accounting, and bounded shutdown. A static inventory audit records which plugins own independent stores.

## Acceptance evidence

`tests/test_storage_hardening.py` covers:

- concurrent migration openers;
- transaction rollback;
- concurrent writers;
- WAL/foreign-key/busy-timeout configuration;
- foreign-key rejection;
- FTS consistency and rebuild;
- verified backup/restore;
- corrupt-backup rejection;
- corrupt-database startup failure;
- plugin-database transaction/backup behavior;
- plugin database-name path traversal rejection.

`tools/storage_hardening_audit.py` is read-only and verifies the implementation contract plus inventories plugin-specific database usage.

The storage hardening block is not complete until both the storage test file and storage audit pass in the local full validation command.
