# AstraUserbot v1.0.0

## Release position

`1.0.0` is the first release candidate for the hardened AstraUserbot platform architecture. It formalizes the existing feature-rich bot around deterministic lifecycle, shared infrastructure, durable work, bounded resources, explicit security boundaries and operational recovery.

## Included

- deterministic plugin discovery, metadata, lifecycle and ownership;
- deterministic command/alias registration and conflict handling;
- bounded TaskSupervisor and production shutdown;
- shared HTTP, subprocess, Telegram, workspace, media and AI services;
- SQLite WAL, numbered/checksummed migrations, integrity and backup/restore gates;
- durable JobEngine with leases, attempt fencing, retries, idempotency, retention and `UNCERTAIN` recovery;
- bounded media downloads/workspaces and artifact verification;
- real Bubblewrap isolation for classified eval/media/OCR child workloads;
- safe ZIP/TAR extraction with traversal/link/special-file rejection;
- provider-independent AI Gateway with bounded remote requests, timeouts, output/context limits and tool-call rejection;
- rebuildable SQLite FTS5 search;
- operator health/status/diagnostics views;
- plugin ecosystem and behavioral audits;
- production operator, upgrade and disaster-recovery documentation;
- executable non-destructive production acceptance gate.

## Intentional compatibility boundaries

The four legacy provider-specific AI modules remain quarantined:

```text
plugins.ai.ask
plugins.ai.groq_client
plugins.ai.summarize
plugins.ai.transcribe
```

Their quarantine is part of the release contract.

## Acceptance

The release must not be tagged until `PRODUCTION_ACCEPTANCE_PASS` and the manual production acceptance checklist both pass.

## Rollback

Use the previous known-good Git commit/tag together with a compatible verified database backup. External Telegram/provider side effects require separate reconciliation.

## Cost

The architecture remains ₹0/$0. Remote AI is optional and bounded; no paid service is mandatory.
