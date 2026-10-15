# AstraUserbot v1.0.1

## Release position

`1.0.1` is the next patch release candidate after the existing `v1.0.0` tag. This release line closes the post-Phase-10 implementation and hardening work that accumulated after v1.0.0 while preserving the single-process, local-first architecture.

## Included

- complete command-contract and discoverability surfaces;
- unified FTS5 search across command, plugin, Telegram, intelligence, evidence, case and media domains;
- unified entity inspection and correlation UX with explicit evidence-state boundaries;
- shared interactive Telegram UX primitives and durable-job controls;
- plugin catalog, lifecycle, dependency and compatibility controls;
- provider-neutral AI product UX with bounded context and advisory-only authority;
- operator control-plane surfaces for doctor, configuration, update and restart workflows;
- durable JobEngine hardening, lease fencing, retry/uncertainty recovery and bounded shutdown;
- Telegram event journal/projection/replay and governed transport;
- IntelGraph, IOC, public/security intelligence, media intelligence and case services;
- bounded media workspaces and real Bubblewrap isolation;
- SQLite/WAL migrations, checksums, integrity, backup/restore and rebuildable FTS5;
- plugin, media, isolation, storage, job and production hardening audits;
- repository CI verification with the complete 14-gate production acceptance contract;
- pinned Ruff development tooling so the documented acceptance gate is reproducible from a clean environment.

## Verification

The current GitHub `main` passes:

- production acceptance Gate 1/14 through Gate 14/14;
- full regression: 359 tests passed;
- Python compilation;
- plugin behavior/ecosystem audits;
- media pipeline audit;
- isolation/security audit;
- storage hardening audit;
- durable job hardening audit;
- Phase 18 production audit;
- bounded shutdown probe.

The remaining release blocker is intentionally external to repository-only CI: owner-host Telegram and systemd acceptance using the real configured session and production environment.

## Compatibility

- Python follows the repository environment.
- Telethon remains the Telegram transport contract.
- SQLite/WAL remains the durable source of truth.
- Plugin API major version remains `1`.
- No second workflow/job system or paid service is introduced.

## Cost

The architecture remains ₹0/$0. Remote AI is optional and bounded; local AI remains supported.

## Release rule

Do not create the immutable `v1.0.1` tag until the owner-host live acceptance checklist passes.
