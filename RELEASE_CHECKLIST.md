# AstraUserbot — Release Checklist

**Current release candidate:** `1.0.0`  
**Tag:** `v1.0.0` (create only after the acceptance gate passes)  
**Cost target:** ₹0 / $0

## 1. Repository and scope

- [ ] `git status --short` is clean or every intentional local change is documented.
- [ ] Release commit is identified and reviewable.
- [ ] No secrets, Telegram session material, production DB dumps, logs or cache artifacts are tracked.
- [ ] No paid dependency/service has been introduced.
- [ ] Version in `VERSION` matches the intended release.

## 2. Architecture and behavior

- [ ] `ARCHITECTURE.md` matches implemented service boundaries.
- [ ] `DATA_MODEL.md`, `JOB_MODEL.md`, `SAFETY_CONTRACT.md` and `PRODUCTION_BOUNDARY.md` match implementation.
- [ ] Plugin lifecycle/ownership is deterministic.
- [ ] No unexpected command/event ownership conflicts.
- [ ] Shared HTTP/subprocess/media/AI boundaries are used where required.
- [ ] Resource limits are bounded.
- [ ] AI remains advisory and tool/function-call execution is disabled.
- [ ] Isolation claims match actual Bubblewrap enforcement.

## 3. Automated verification

Run from the repository root:

```bash
./venv/bin/python tools/production_acceptance_gate.py
```

This is the canonical non-destructive acceptance gate. It runs the full test suite, compile validation, plugin behavior/ecosystem audits, media, isolation, storage, durable-job, Phase 18 production audits and the bounded shutdown probe.

The following individual commands are useful for diagnosis:

```bash
./venv/bin/python -m pytest -q
./venv/bin/python -m compileall -q core plugins tools
./venv/bin/python tools/plugin_behavior_audit.py
./venv/bin/python tools/plugin_ecosystem_audit.py
./venv/bin/python tools/media_pipeline_audit.py
./venv/bin/python tools/isolation_security_audit.py
./venv/bin/python tools/storage_hardening_audit.py
./venv/bin/python tools/job_hardening_audit.py
./venv/bin/python tools/phase18_production_audit.py
./venv/bin/python tools/phase18_shutdown_probe.py
```

- [ ] `PRODUCTION_ACCEPTANCE_PASS` recorded.

## 4. Backup and database

- [ ] Verified database backup created before production restart.
- [ ] Migration/integrity check passes.
- [ ] No unexplained `UNCERTAIN` jobs.
- [ ] Search/index rebuild path is known.

```bash
./venv/bin/python -m tools.astra_platform backup data/backups/platform_$(date -u +%Y%m%dT%H%M%SZ).db
./venv/bin/python -m tools.astra_platform migrate
```

## 5. Production acceptance

- [ ] `astra.service` is active.
- [ ] Telegram is connected/authorized.
- [ ] Database reports PASS.
- [ ] Required services are initialized.
- [ ] `.health` passes.
- [ ] `.plugins` has no unexpected failures/quarantine changes.
- [ ] `.jobs` and `.tasks` show no unexplained work.
- [ ] `.status` reports no unexpected operator attention.
- [ ] `.diagnostics` is secret-safe.
- [ ] Representative owner smoke tests pass.
- [ ] Controlled restart completes without systemd timeout or forced kill.

## 6. Release artifact

- [ ] `VERSION` is `1.0.0`.
- [ ] Release notes/changelog entry exists in commit history or release record.
- [ ] Previous known-good commit/tag is recorded.
- [ ] Compatible rollback backup is retained.
- [ ] `v1.0.0` tag is created **after** acceptance passes and points at the accepted release commit.

## 7. Release blockers

Do not release when any required gate fails, a backup is unverified, a migration checksum fails, a secret is exposed, shutdown is forced, an isolated workload can silently bypass isolation, or an external side effect remains unexplained/uncertain.
