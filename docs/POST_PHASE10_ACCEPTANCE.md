# Post-Phase-10 Maturity Acceptance

This document is the acceptance ledger for Gates A–H in `ROADMAP_POST_PHASE10.md`.

## Current implementation checkpoint

The A–H implementation program is now **code-complete at the repository contract level**.

The remaining acceptance work is deliberately limited to validation that requires the owner's local runtime, Telegram session, configured provider, systemd environment, or external services. It is not represented as complete until those validations are actually run.

## Gate A — Command Contract + Discoverability

Implemented surfaces:

- canonical command identity
- aliases
- plugin/category ownership
- operation class
- permission metadata
- examples
- compatibility metadata
- network/job/destructive/confirmation metadata
- bounded command discovery
- `.help`
- `.help <command>`
- `.help <category>`
- `.command search`
- `.command describe`
- `.command examples`
- `.command category`
- `.command aliases`
- `.command permissions`
- `.command source`
- `.command recent`
- deterministic registry collision handling
- privacy-safe command contract with no command arguments stored by the registry
- explicit implementation source references
- explicit compatibility validation

Acceptance evidence:

- [x] live registry remains the command authority
- [x] metadata is derived from registrations
- [x] compatibility defaults are explicit
- [x] operation class is deterministic
- [x] category discovery is distinct from command resolution
- [x] focused contract tests added
- [x] privacy-safe recent discovery tests added
- [x] static A–H maturity audit covers the contract
- [ ] full local regression run
- [ ] owner-host live smoke

## Gate B — Unified Search

Implemented:

- one `SearchService` FTS5 front door
- live command registry indexing
- plugin indexing
- document indexing
- Telegram message indexing
- canonical archive-message indexing
- IntelGraph entity indexing
- intelligence observation indexing
- OCR evidence indexing
- transcript evidence indexing
- case indexing
- media evidence indexing
- security evidence indexing
- bounded source filtering
- deterministic ranking
- stable result IDs
- evidence/reference IDs
- opaque query-bound page cursors
- backward-compatible offset API for internal callers

Acceptance evidence:

- [x] one SearchService front door
- [x] no second search engine
- [x] bounded query/limit
- [x] stable result identity
- [x] source filtering
- [x] cursor validation is query/filter bound
- [x] intelligence/case domains connected
- [x] OCR/transcript evidence connected
- [x] focused cursor/indexing tests added
- [ ] full local regression run
- [ ] owner-host permission/scope smoke

## Gate C — Unified Entity Inspector

Implemented:

- `.inspect`
- URL/domain/IP/username and IntelGraph target resolution
- Telegram-observable target resolution through existing graph/state boundaries
- IOC-prefixed targets
- `message:<id>`
- `media:<ref>`
- `case:<id>`
- `plugin:<name>`
- `command:<name>`
- ambiguous-target handling
- evidence references
- relationship display
- observed/derived/possible/unknown distinction
- explicit no-identity-claim safety boundary

Acceptance evidence:

- [x] existing IntelGraph resolver reused
- [x] no duplicate identity engine
- [x] ambiguous targets are not auto-selected
- [x] evidence/source references retained
- [x] inspector contract documented
- [ ] owner-host target smoke for URL/domain/username/Telegram/entity cases

## Gate D — Correlation / Intelligence UX

Implemented:

- `.correlate`
- existing IntelGraph graph/correlation boundary
- `IntelCorrelationEngine` registered as an explicit ApplicationContext service
- bounded relationship inspection
- relationship type
- evidence state
- confidence
- supporting observation references
- contradiction/unknown classification contract
- explicit interpretation boundary

Acceptance evidence:

- [x] no second correlation engine
- [x] correlation engine is a first-class runtime dependency
- [x] graph evidence is exposed
- [x] confidence is visible
- [x] derived relationships remain distinct
- [x] correlation contract documented
- [ ] owner-host contradiction/unknown live smoke

## Gate E — Interactive UX Maturity

Implemented platform primitives:

- buttons
- bounded pagination
- progress
- cancellation/confirmation primitives
- generic list navigation
- generic form submit/cancel controls
- generic gallery navigation
- bounded callback token helper
- callback token parser/validation
- existing durable job cards/controls retained

Selected high-value workflow migration:

- durable job listing pagination
- durable job status controls
- active-job cancellation confirmation
- retry controls
- durable job lifecycle rendering

Acceptance evidence:

- [x] reusable primitives
- [x] callback payloads remain bounded
- [x] callback parsing is bounded
- [x] durable job UI remains source-of-truth compatible
- [x] selected durable-job workflow uses the shared primitives
- [x] callback contract tests added
- [ ] production callback smoke for the owner's Telegram runtime
- [ ] further optional migration of non-job read-only surfaces

## Gate F — Plugin UX + Compatibility

Implemented:

- `.plugin` catalog
- `.plugin <name>` detail
- `.plugin search <query>`
- `.plugin health <name>`
- `.plugin enable <name>`
- `.plugin disable <name>`
- `.plugin reload <name>`
- `.plugin install <name>` as safe local-discovered enable
- dependency protection
- quarantine protection
- existing compatibility metadata
- plugin command ownership
- lifecycle state visibility
- plugin health/error visibility
- no blind package installation

Acceptance evidence:

- [x] lifecycle uses existing PluginManager
- [x] dependencies are enforced
- [x] quarantine remains hard
- [x] no blind package installation
- [x] plugin UX contract documented
- [x] plugin SDK foundation remains the compatibility authority
- [ ] full lifecycle live smoke
- [ ] owner-host compatibility migration audit

## Gate G — AI Product UX

Implemented:

- `.aiux summarize`
- `.aiux explain`
- `.aiux search`
- `.aiux evidence`
- `.aiux case`
- `.aiux timeline`
- `.aiux media`
- reply/message bounded context
- search-to-AI synthesis
- evidence explanation
- case report drafting
- timeline summary
- OCR/STT → AI path
- provider-neutral AI gateway
- explicit advisory-only boundary
- no direct Telegram mutation

Acceptance evidence:

- [x] existing AIService reused
- [x] existing media intelligence reused
- [x] AI receives bounded context
- [x] evidence references retained in synthesis prompts
- [x] AI cannot bypass command/traffic policy
- [x] AI product contract documented
- [ ] live provider smoke
- [ ] live media OCR/STT smoke

## Gate H — Operator / Control Plane

Implemented:

- `.doctor`
- `.config`
- `.update check`
- `.update apply`
- `.restart confirm`
- existing `.health`
- existing `.status`
- existing `.plugins`
- existing `.jobs`
- existing diagnostics
- safe configuration display
- database integrity check
- search readiness
- AI diagnostics
- isolation diagnostics
- plugin health
- job sampling
- dirty-worktree update guard
- fast-forward-only update
- explicit restart confirmation
- first-run/operator preflight documentation

Acceptance evidence:

- [x] diagnostics remain secret-safe
- [x] update refuses dirty worktree
- [x] update uses fast-forward-only pull
- [x] restart is explicit
- [x] existing operator surfaces remain intact
- [x] first-run/preflight contract documented
- [ ] owner-host systemd smoke
- [ ] update/restart recovery smoke

## Product Maturity Gate

The implementation is not considered release-accepted merely because source changes exist.

Final closure requires:

1. focused maturity tests;
2. full regression;
3. compileall;
4. plugin ecosystem audit;
5. media pipeline audit;
6. isolation audit;
7. storage/search audit;
8. production acceptance;
9. owner-host live Telegram smoke;
10. documentation synchronization.

The repository now contains a static A–H audit:

`python tools/post_phase10_maturity_audit.py`

The remaining Dataset/Hugging Face lineage track is intentionally separate and remains blocked until its account-census and lineage prerequisites are completed.

## Recommended local acceptance sequence

From a clean checkout:

```bash
python tools/post_phase10_maturity_audit.py
ruff check .
ruff format --check .
python -m compileall -q .
python -m pytest -q tests/test_post_phase10_maturity.py tests/test_phase10_15_gate.py tests/test_runtime_services.py tests/test_phase16_gate.py
python -m pytest -q
```

Then perform the owner-host/live gates:

```text
A: .help / .command discovery smoke
B: .search cross-domain + permission/scope smoke
C: .inspect URL/domain/username/Telegram/entity cases
D: .correlate observed/derived/contradicted/unknown cases
E: job buttons/pagination/confirmation/cancellation/retry
F: plugin catalog/detail/search/health/enable/disable/reload lifecycle
G: AI provider + OCR/STT product smoke
H: .doctor/.status/.health/.jobs/.plugins/.update check/.restart confirm
systemd restart + recovery validation
```

## Governing rule

```
implemented
    !=
verified
    !=
accepted
```

The code in this gate is the implementation baseline. Local/owner-host validation is the final acceptance authority.

## Roadmap crosswalk

The A–H program maps to the existing competitive maturity gates as follows:

- UX-MATURITY-1 → Gate A command discovery and searchable help;
- UX-MATURITY-2 → Gate E shared buttons/pagination/confirmation/progress primitives;
- UX-MATURITY-3 → Gate E forms/galleries/lists primitives and selected high-value workflow migration;
- UX-MATURITY-4 → Gate F plugin catalog/detail/lifecycle/compatibility;
- UX-MATURITY-5 → moderation audit/bounds plus permission/target preflight;
- UX-MATURITY-6 → Gate G bounded AI reply/search/evidence/case/timeline/media flows;
- UX-MATURITY-7 → Gate H update/config/restart/doctor;
- UX-MATURITY-8 → Gate H first-run/operator preflight documentation;
- UX-MATURITY-9 → Product Maturity acceptance after focused/full/live validation.

The existing Program F `.rewrite`, `.translate`, `.extract`, and `.code` surfaces remain on the unified AI gateway and are not replaced by `aiux`; the new `aiux` commands add product-integrated context/evidence/case/media workflows.
