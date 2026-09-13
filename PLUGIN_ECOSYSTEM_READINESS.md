# Plugin Ecosystem Quality — Readiness

**Status: IMPLEMENTED — VALIDATION REQUIRED**

This is the current plugin-platform quality gate. It is intentionally separate from the historical numbered phase documents.

## Contract completed

- `core/plugins/contract.py` defines the formal metadata vocabulary and API version.
- Legacy setup-only plugins receive deterministic compatibility metadata without a risky mass rewrite.
- Required dependencies are ordered deterministically; unknown dependencies and cycles fail closed.
- Optional dependencies and capabilities are represented in plugin records.
- Setup/shutdown lifecycle ownership remains centralized in `PluginManager`.
- Command ownership remains centralized in `core.registry`.
- Plugin snapshots expose lifecycle and contract metadata.
- Quarantined AI modules remain a hard runtime boundary.
- Async enable/disable operations protect dependency relationships, bound setup/shutdown, and roll back failed activation registrations.
- A read-only AST audit covers the complete active plugin tree without importing feature modules.

## Safe mutation contract

Use `disable_plugin()` and `enable_plugin()` for new runtime controls. They are deliberately asynchronous because safe mutation requires real lifecycle work, not merely flipping a boolean.

A plugin is never considered successfully enabled after a partial setup. A plugin with running dependents cannot be disabled. Quarantined modules cannot be enabled.

The old synchronous `enable()` / `disable()` methods are compatibility markers only and must not be used for new operator controls.

## Validation gate

```bash
cd ~/AstraUserbot && \
git pull --ff-only origin main && \
./venv/bin/python -m pytest -q && \
./venv/bin/python tools/plugin_ecosystem_audit.py && \
./venv/bin/python tools/media_pipeline_audit.py && \
./venv/bin/python tools/isolation_security_audit.py && \
./venv/bin/python tools/storage_hardening_audit.py && \
./venv/bin/python tools/job_hardening_audit.py && \
./venv/bin/python tools/phase18_production_audit.py
```

Required new result:

```text
PLUGIN_ECOSYSTEM_QUALITY_AUDIT_PASS
```

All existing gates must remain green. No plugin is reactivated merely because it passes structural checks; the four legacy AI modules remain quarantined until their gateway migration is separately approved.
