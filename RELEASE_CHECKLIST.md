# AstraUserbot Release Checklist

## Research / audit

- [ ] Review roadmap and architecture contracts.
- [ ] Review changed commands and ownership conflicts.
- [ ] Review dependency and cost impact.

## Code

- [ ] No secrets/session files staged.
- [ ] No new paid service dependency.
- [ ] Shared HTTP/subprocess/media/AI boundaries are used.
- [ ] Resource limits are bounded.
- [ ] Durable work has persistence and verification semantics.
- [ ] Search remains rebuildable.
- [ ] Feature flags have safe defaults.
- [ ] Isolation claims match actual enforcement.

## Verification

```bash
python -m unittest discover -s tests -v
python -m unittest tests.test_phase10_15_gate -v
python -m compileall -q .
python -m tools.astra_platform selftest
python -m tools.astra_platform benchmark
python -m tools.astra_platform migrate
```

- [ ] Service startup/shutdown smoke test.
- [ ] `.health` passes.
- [ ] `.plugins` has no unexpected failures.
- [ ] `.diagnostics` report is secret-safe.
- [ ] Search rebuild succeeds.
- [ ] Backup creation and integrity check succeed.

## Release

- [ ] Git diff reviewed.
- [ ] Commit history is coherent.
- [ ] Documentation updated.
- [ ] Rollback commit identified.
- [ ] Backup exists before production restart.
- [ ] Restart performed only after verification.
