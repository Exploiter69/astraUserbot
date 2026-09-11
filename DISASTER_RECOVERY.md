# AstraUserbot Disaster Recovery

## What is authoritative

Telegram and external providers remain authoritative. Astra's SQLite database stores durable operational state; search indexes and caches are derived.

## Before recovery

1. Stop the bot cleanly when possible.
2. Preserve the current database and logs.
3. Do not delete the Telegram session.
4. Record the current Git commit.

## Database backup

```bash
python -m tools.astra_platform backup data/backups/platform_$(date -u +%Y%m%dT%H%M%SZ).db
```

The backup command uses SQLite's backup API rather than copying a live WAL database blindly.

## Integrity check

```bash
python -m tools.astra_platform migrate
```

A failed integrity check blocks normal release verification.

## Restore procedure

1. Stop Astra.
2. Preserve the damaged database as evidence.
3. Restore a known-good backup to a separate file.
4. Run the migration/integrity check against the restored database.
5. Review jobs in `UNCERTAIN` state before replay.
6. Rebuild search indexes after restore with `.reindex`.
7. Start Astra and perform owner smoke tests.

Never automatically replay uncertain external mutations after restore.

## Plugin failure

Use `.plugins` and `.diagnostics` to identify failed setup/import state. Disable the affected plugin through the controlled plugin lifecycle rather than deleting files while the process is live.

## Rollback

Rollback means reverting to a known Git commit and restoring compatible platform state. Never mix a newer database schema with an older application commit unless the migration compatibility policy explicitly allows it.
