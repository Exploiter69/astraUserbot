# AstraUserbot — Phase 9 Readiness

**Phase:** 9 — Plugin Migration Program  
**Status:** Implementation complete; Gate 9 pending local validation  
**Cost target:** ₹0 / $0

## Objective

Move the existing plugin ecosystem onto the shared platform services without changing intended user-facing behavior.

## Migration Matrix

| Batch | Scope | Status |
|---|---|---|
| A | Security/Admin | Complete from Phases 6–8; regression coverage retained |
| B | Network/OSINT | Complete: DNS, headers, IP info, OSINT recon, speedtest now use shared HTTP/subprocess services |
| C | Media | Complete from Phase 7; media consumers use MediaService |
| D | System/Automation | Complete for shared-infrastructure consumers; OCR/sysinfo/backup/speedtest migrated to shared workspace/subprocess boundaries |
| E | AI/Advanced | AI command path complete from Phase 8; legacy Groq compatibility modules remain quarantined until compatibility exit criteria |

## Required Invariants

1. Active plugins must not create their own HTTP sessions when `HttpService` is the platform boundary.
2. Active plugins must not invoke subprocesses through `helpers.shell`; `SubprocessService` is authoritative.
3. Media workloads use `MediaService` for media execution, bounded workspaces, artifact verification and cleanup.
4. Active AI commands use `AIService`; provider-specific command code remains quarantined compatibility only.
5. Plugin behavior remains user-facing compatible except for confirmed reliability/security fixes.
6. Resource limits, cancellation and failure translation remain owned by shared services.
7. No paid infrastructure or mandatory paid provider is introduced.

## Gate 9

Run:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m compileall -q core helpers plugins
python -m unittest tests.test_phase9_gate -v
```

The gate checks the migration boundary statically and exercises representative service contracts. A passing Gate 9 requires the complete suite to remain green and the phase-specific migration assertions to pass.

## Compatibility Exit

The legacy AI/Groq compatibility artifacts are intentionally retained until the active command path has been validated in production and the compatibility exit criteria are explicitly met. Phase 9 does not delete them merely to make the source tree look clean.
