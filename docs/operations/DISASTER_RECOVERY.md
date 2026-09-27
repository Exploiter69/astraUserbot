# AstraUserbot — Backup, Restore & Disaster Recovery

**Release line:** 1.0.x  
**Cost target:** ₹0 / $0

## 1. Authority and recovery principles

Telegram and external providers remain authoritative for their own state. Astra's SQLite database is authoritative for Astra operational state. Cache and search indexes are derived and rebuildable.

Recovery follows:

```text
CONTAIN → PRESERVE → CLASSIFY → RESTORE/REPAIR → VERIFY → REPORT
```

Never convert an unknown external outcome into success merely because a local job record says it should have completed.

## 2. Immediate containment

If Astra is producing unsafe/destructive behavior:

```bash
sudo systemctl stop astra.service
systemctl is-active astra.service || true
```

Preserve the current database, WAL/SHM files, relevant logs and the current Git commit. Do not delete the Telegram session as a first response.

## 3. Pre-recovery evidence

Record:

```bash
git rev-parse HEAD
systemctl status astra.service --no-pager
journalctl -u astra.service --since '30 min ago' --no-pager
```

If the database may be corrupt, preserve the complete database set before attempting repair.

## 4. Verified database backup

Use the platform backup command. Do not blindly copy a live WAL database with `cp`.

```bash
./venv/bin/python -m tools.astra_platform backup data/backups/platform_$(date -u +%Y%m%dT%H%M%SZ).db
```

A backup is not considered valid until the platform backup/integrity contract succeeds.

## 5. Integrity and migration check

```bash
./venv/bin/python -m tools.astra_platform migrate
```

A migration checksum mismatch is a release-blocking integrity failure. Historical migrations must never be edited to make the current database pass.

## 6. Restore procedure

1. Stop Astra.
2. Preserve the damaged database and associated WAL/SHM files.
3. Select a known-good backup compatible with the application release.
4. Restore to a separate candidate path first.
5. Run integrity and migration checks against the candidate.
6. Confirm schema compatibility before replacing the active database.
7. Inspect jobs, especially `UNCERTAIN`, before starting production.
8. Rebuild derived search state after restore with `.reindex`.
9. Start Astra.
10. Run `.health`, `.plugins`, `.jobs`, `.diagnostics` and targeted owner smoke tests.
11. Record the restored backup, Git commit and verification result.

Never overwrite the only copy of the damaged database during the first restore attempt.

## 7. Uncertain jobs after recovery

An expired lease, interrupted active operation or ambiguous external response can leave a job `UNCERTAIN`.

Required sequence:

```text
inspect job
   ↓
identify external side effect
   ↓
query/reconcile authoritative external state
   ↓
determine whether mutation happened
   ↓
only then requeue if a safe idempotent action remains
```

Do not automatically replay Telegram sends, deletes, permission changes, uploads, posts or other external mutations merely because a worker disappeared.

## 8. Plugin recovery

Use `.plugins` and `.diagnostics` to identify `FAILED_IMPORT`, `FAILED_SETUP`, `DISABLED`, or quarantined state.

Repair source/config offline, run the release gate, then restart. Do not delete plugin files from a live process.

Quarantined legacy AI modules remain quarantined unless a separately reviewed migration changes that contract.

## 9. Cache/search recovery

Cache and FTS/search state are derived.

If corrupted:

```text
preserve evidence if useful
      ↓
clear/rebuild derived state
      ↓
verify authoritative source records
```

Never modify authoritative records merely to match a corrupted cache or index.

## 10. Filesystem/media recovery

Managed media workspaces are disposable. If disk pressure is severe, stop new bulk work and clean only managed temporary/cache artifacts. Do not delete the authoritative database, source files or Telegram session as a space-saving shortcut.

Malformed archives/media must be rejected by the existing safety boundary rather than extracted/decoded with an ad-hoc command.

## 11. Credential compromise

If a secret is suspected exposed:

1. stop the affected runtime;
2. preserve evidence without redistributing the secret;
3. rotate/revoke the credential at its authoritative provider;
4. replace the runtime secret securely;
5. inspect logs/repository history for additional exposure;
6. run the release/security gates;
7. restart and verify.

Never place credentials into Git, diagnostics, AI prompts, issue text, or Telegram messages.

## 12. Rollback

Rollback consists of a compatible Git commit plus compatible durable state.

```text
known-good code
      +
compatible database/backup
      +
verified configuration
      =
rollback candidate
```

Do not run an older application against a newer incompatible database schema. Do not assume a Git rollback alone reverses external Telegram/provider side effects.

## 13. Recovery completion criteria

Recovery is complete only when:

- service is active and stable;
- database integrity passes;
- required plugins are running;
- no unexpected command conflicts exist;
- jobs have no unexplained `UNCERTAIN` outcomes;
- search/indexes are rebuilt if required;
- isolation is available for workloads requiring it;
- diagnostics are secret-safe;
- owner smoke tests pass;
- recovery commit/backup/evidence is recorded.
