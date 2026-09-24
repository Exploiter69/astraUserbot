# AstraUserbot — Production Operator Runbook

**Release line:** 1.0.x  
**Cost target:** ₹0 / $0  
**Audience:** owner/operator of the production userbot

## 1. Operating contract

Astra is a single-process Python/asyncio Telegram userbot. SQLite is the durable local store; caches and search indexes are derived; process-local tasks are ephemeral; restart-sensitive work belongs to the JobEngine. Plugins are not process-isolated trust boundaries.

The operator must prefer **inspect → verify → act → verify again** over blind repair.

Never expose the Telegram session, API keys, cookies, passwords, private keys, or secret-bearing payloads in Telegram, logs, diagnostics, tickets, or commits.

## 2. Normal startup

Production is managed by systemd. The expected service is `astra.service`.

```bash
systemctl is-active astra.service
systemctl status astra.service --no-pager
journalctl -u astra.service -n 80 --no-pager
```

Healthy startup should show Telegram connected/authorized, database integrity PASS, shared services initialized, active plugins reported, and the startup HUD ending in `SYSTEM READY`.

## 3. First-response triage

Run the read-only operator views in Telegram:

```text
.status
.health
.plugins
.tasks
.jobs
.diagnostics
```

Interpretation:

| Signal | Meaning | First action |
|---|---|---|
| Database FAIL | persistence may be unsafe | stop mutations; preserve DB; follow recovery runbook |
| Plugin FAILED_SETUP/FAILED_IMPORT | feature unavailable | inspect `.plugins`/`.diagnostics`; isolate the plugin |
| Job UNCERTAIN | external outcome is unknown | reconcile before replay |
| Job RETRYING | bounded retry is scheduled | inspect error/backoff; do not duplicate manually |
| Isolation unavailable | classified isolated work must not fall back | restore Bubblewrap capability or disable feature |
| AI unavailable | AI feature degradation | continue non-AI operation; inspect provider/guardrail state |
| Tasks unexpectedly growing | lifecycle/backpressure issue | inspect `.tasks`; do not restart repeatedly |

## 4. Safe restart

Use a controlled restart only after checking `.health` and `.jobs`.

```bash
sudo systemctl restart astra.service
systemctl is-active astra.service
journalctl -u astra.service -n 80 --no-pager
```

A successful stop must not show `stop-sigterm timed out`, `Killing`, or a failed systemd result.

## 5. Logs

```bash
journalctl -u astra.service --since '15 min ago' --no-pager
journalctl -u astra.service -p warning --since '1 hour ago' --no-pager
```

Look for stable error classes/correlation IDs. Do not paste unredacted logs into external services.

## 6. Plugin operations

Use `.plugins` for state and metadata. Controlled runtime enable/disable exists only through the Plugin Manager lifecycle and must respect dependencies and quarantine rules.

Never edit or delete a plugin file while production is running as a recovery technique. Stop the service, preserve evidence, change source, test, then restart.

The four legacy AI modules remain intentionally quarantined:

```text
plugins.ai.ask
plugins.ai.groq_client
plugins.ai.summarize
plugins.ai.transcribe
```

Do not remove the quarantine merely because an AI command is unavailable.

## 7. Job operations

`.jobs` is the first operator view. Job states have durable semantics:

```text
QUEUED → RUNNING → VERIFYING → COMPLETED
             ├→ QUEUED (retry)
             ├→ UNCERTAIN
             ├→ FAILED
             └→ CANCELLED
```

`UNCERTAIN` means the external effect cannot safely be assumed. Reconcile the external system first; only then requeue with explicit operator intent.

Never create a second job to “make sure” a possibly completed external mutation happened.

## 8. Database checks

The database is authoritative for Astra operational state. Before repair:

1. stop Astra if corruption or restore is suspected;
2. preserve the current DB and WAL/SHM files as evidence;
3. make a fresh backup if the DB is readable;
4. run the documented integrity/migration checks;
5. restore only after selecting a known-good backup.

Do not manually edit SQLite rows to force a job or plugin state.

## 9. Backup

Create a verified backup using the platform command, not `cp` against a live WAL database:

```bash
python -m tools.astra_platform backup data/backups/platform_$(date -u +%Y%m%dT%H%M%SZ).db
```

After backup, preserve the artifact outside the active working database path and verify it according to `DISASTER_RECOVERY.md`.

## 10. Upgrade

Normal upgrade sequence:

```bash
git status --short
git fetch origin
git diff --exit-code origin/main..HEAD
```

Review the release commit/tag, create a verified DB backup, then:

```bash
git pull --ff-only origin main
./venv/bin/python -m pytest -q
./venv/bin/python -m compileall -q core plugins tools
./venv/bin/python tools/production_acceptance_gate.py
```

Only after the gate passes should production be restarted.

## 11. Resource pressure

Astra intentionally uses bounded concurrency, output, media, AI, job, cache, and disk policies. If the host is under pressure:

1. stop initiating new bulk work;
2. inspect `.tasks`, `.jobs`, `.cache`, `.stats`;
3. preserve the DB;
4. allow bounded cleanup/recovery;
5. restart only if the process is unhealthy.

Do not raise limits simply to make a failing operation complete.

## 12. Emergency stop

If Astra is behaving destructively or credentials are suspected compromised:

```bash
sudo systemctl stop astra.service
systemctl is-active astra.service || true
```

Then preserve logs/database/session state as appropriate. Rotate compromised credentials outside the repository. Do not delete evidence before diagnosis.

## 13. Escalation rule

When the outcome is unknown, stop and reconcile. When the target or authorization is unknown, refuse. When resources are exhausted, backpressure. When a release gate fails, do not bypass the gate for production convenience.

## 14. Quick health gate

A release-quality runtime should satisfy:

```text
service active
Telegram connected
DB integrity PASS
all required services started
no unexpected plugin failures
no unexpected command conflicts
no unbounded tasks/jobs
isolation available for isolated workloads
AI guardrails active when AI is enabled
backup/recovery path known
```


## Post-Phase-10 operator control surface

Additional owner-facing controls:

- `.doctor` — safe platform diagnostics;
- `.config` — redacted configuration view;
- `.update check` — clean-tree/update preflight;
- `.update apply` — fast-forward-only update after clean-tree preflight;
- `.restart confirm` — explicit supervisor-compatible restart request.

These controls reuse existing storage, search, AI, isolation, plugin and process lifecycle boundaries. Update never falls back to a destructive merge or reset.
