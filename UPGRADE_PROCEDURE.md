# AstraUserbot — Production Upgrade Procedure

**Release line:** 1.0.x  
**Principle:** verify first, mutate production second.

## 1. Pre-flight

Confirm:

- current service is healthy;
- current Git commit is known;
- a verified database backup exists;
- the target release/tag is known;
- rollback commit/tag and compatible backup are known;
- no local production edits will be overwritten.

```bash
git status --short
git rev-parse HEAD
systemctl is-active astra.service
```

## 2. Create a release backup

```bash
./venv/bin/python -m tools.astra_platform backup data/backups/platform_$(date -u +%Y%m%dT%H%M%SZ).db
```

Keep the backup until post-upgrade acceptance is complete.

## 3. Fetch and verify source

```bash
git fetch origin --tags
git status --short
git log -1 --oneline
```

For a clean release checkout, fast-forward only:

```bash
git pull --ff-only origin main
```

Do not use `git reset --hard` as a normal upgrade operation.

## 4. Run the release gate before restart

```bash
./venv/bin/python tools/production_acceptance_gate.py
```

A failure blocks production restart. Diagnose and fix the release candidate rather than bypassing the failing gate.

## 5. Restart

```bash
sudo systemctl restart astra.service
systemctl is-active astra.service
journalctl -u astra.service -n 100 --no-pager
```

Expected: clean stop, successful start, Telegram connected, database PASS, required plugins/services healthy.

## 6. Post-upgrade smoke test

From the owner account:

```text
.health
.plugins
.jobs
.tasks
.status
.diagnostics
```

Check a representative read-only command and one representative non-destructive feature from each changed plugin family.

## 7. Rollback

If acceptance fails after restart:

1. stop the service;
2. preserve logs and the failed-release database state;
3. checkout the previous known-good commit/tag;
4. verify database compatibility;
5. restore the compatible backup only when required;
6. run the acceptance gate against the rollback candidate;
7. restart and repeat owner smoke tests.

Git rollback does not undo external Telegram/provider side effects. Reconcile those independently.

## 8. Migration safety

Database migrations are numbered and checksum-protected. Never edit an already-applied historical migration to force compatibility. If the target release cannot safely consume the existing database, stop and select a compatible migration/backup path.

## 9. Release completion

Record:

```text
old commit/tag
new commit/tag
backup artifact
migration result
acceptance result
restart result
smoke-test result
UTC timestamp
```

Keep the rollback artifact until the release has remained healthy for the chosen observation window.
