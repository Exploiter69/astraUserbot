# AstraUserbot — Production Acceptance Gate

**Release candidate:** 1.0.0  
**Cost target:** ₹0 / $0  
**Acceptance rule:** every required automated gate must pass; manual production checks must be explicitly recorded as PASS.

## 1. Automated acceptance

Run from the repository root with the project virtual environment:

```bash
./venv/bin/python tools/production_acceptance_gate.py
```

The gate runs:

- full pytest suite;
- compile validation;
- plugin behavior audit;
- plugin ecosystem audit;
- media pipeline audit;
- isolation/security audit;
- storage/database audit;
- durable job audit;
- Phase 18 production audit;
- bounded shutdown probe.

A non-zero result blocks release.

## 2. Manual production acceptance

The automated gate does not mutate or restart the production system. After it passes:

### Service

```bash
systemctl is-active astra.service
systemctl status astra.service --no-pager
journalctl -u astra.service -n 80 --no-pager
```

Expected: active service, Telegram connected, database PASS, required services running, no unexpected plugin failures.

### Telegram smoke

Run as owner:

```text
.help
.health
.plugins
.tasks
.jobs
.status
.diagnostics
```

Expected: commands respond; no unexpected plugin failures; no unexplained jobs/tasks; diagnostics remain secret-safe.

### Controlled restart

```bash
sudo systemctl restart astra.service
systemctl is-active astra.service
journalctl -u astra.service -n 80 --no-pager
```

Expected: clean shutdown followed by successful startup. A release is rejected if systemd reports a stop timeout, forced kill, or failed service state.

### Backup

Create and retain a verified backup before the release is declared production-ready:

```bash
./venv/bin/python -m tools.astra_platform backup data/backups/platform_$(date -u +%Y%m%dT%H%M%SZ).db
```

### Search/rebuild

Use `.reindex` only after confirming the source records are healthy. Search indexes are derived and must be rebuildable.

## 3. Release blockers

Reject the release if any of these are true:

- test or audit failure;
- uncommitted production code/config changes not intentionally documented;
- secret/session material tracked by Git;
- unexpected plugin/command conflict;
- database integrity failure or migration checksum mismatch;
- unexplained `UNCERTAIN` durable jobs;
- isolated workload would silently run without its required isolation backend;
- AI tool/function-call execution path exists;
- cost/request guardrails are disabled for remote AI;
- backup is missing or unverified;
- production shutdown is forced or times out;
- documentation does not match the release behavior.

## 4. Acceptance record

Record the following with the release:

```text
Version: 1.0.0
Git commit: <accepted commit>
Git tag: v1.0.0
Automated gate: PASS
Production service: PASS
Telegram smoke: PASS
Backup: PASS
Controlled restart: PASS
Operator: <owner>
UTC timestamp: <timestamp>
```

## 5. Rollback decision

Before restart, identify:

- previous known-good Git commit/tag;
- compatible database backup;
- configuration source;
- rollback owner decision.

Rollback is not complete until the older application, compatible database state and external side effects are separately verified.
