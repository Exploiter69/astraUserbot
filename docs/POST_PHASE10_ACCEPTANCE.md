# Post-Phase-10 Maturity Acceptance

This document is the acceptance ledger for Gates A–H in `ROADMAP_POST_PHASE10.md`.

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
- `.command search`
- `.command describe`
- `.command examples`
- `.command category`
- `.command aliases`
- `.command permissions`
- `.command source`
- deterministic registry collision handling
- privacy-safe command contract (no command arguments stored by the registry)

Acceptance evidence:

- [x] live registry remains the command authority
- [x] metadata is derived from registrations
- [x] compatibility defaults are explicit
- [x] operation class is deterministic
- [x] focused contract tests added
- [ ] full local regression run
- [ ] owner-host live smoke

## Gate B — Unified Search

Implemented:

- live command registry indexing
- plugin indexing
- document indexing
- message indexing
- IntelGraph entity indexing
- intelligence observation indexing
- case indexing
- bounded source filtering
- deterministic pagination
- stable result IDs
- evidence/reference IDs
- ranking through SQLite FTS5

Acceptance evidence:

- [x] one SearchService front door
- [x] no second search engine
- [x] bounded query/limit/offset
- [x] stable result identity
- [x] source filtering
- [x] intelligence/case domains connected
- [ ] full local regression run
- [ ] live permission/scope smoke

## Gate C — Unified Entity Inspector

Implemented:

- `.inspect`
- case inspection
- plugin inspection
- command inspection
- IntelGraph target resolution
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
- [ ] owner-host target smoke for URL/domain/username/Telegram/entity cases

## Gate D — Correlation / Intelligence UX

Implemented:

- `.correlate`
- existing IntelGraph graph/correlation engine reused
- relationship type
- evidence state
- confidence
- related entity display
- explicit interpretation boundary

Acceptance evidence:

- [x] no second correlation engine
- [x] graph evidence is exposed
- [x] confidence is visible
- [x] derived relationships remain distinct
- [ ] contradiction/unknown live smoke

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
- existing durable job cards/controls retained

Acceptance evidence:

- [x] reusable primitives
- [x] callback payloads remain bounded
- [x] durable job UI remains source-of-truth compatible
- [ ] migrate all selected high-value workflows
- [ ] production callback smoke

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
- existing plugin ecosystem audit

Acceptance evidence:

- [x] lifecycle uses existing PluginManager
- [x] dependencies are enforced
- [x] quarantine remains hard
- [x] no blind package installation
- [ ] full lifecycle live smoke
- [ ] compatibility migration audit

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
- [x] evidence references retained in synthesis prompt
- [x] AI cannot bypass command/traffic policy
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

Acceptance evidence:

- [x] diagnostics remain secret-safe
- [x] update refuses dirty worktree
- [x] update uses fast-forward-only pull
- [x] restart is explicit
- [x] existing operator surfaces remain intact
- [ ] owner-host systemd smoke
- [ ] update/restart recovery smoke

## Product Maturity Gate

The implementation is not considered release-accepted merely because the source changes exist.

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

The remaining Dataset/Hugging Face lineage track is intentionally separate and remains blocked until its account-census and lineage prerequisites are completed.

## Governing rule

```
implemented
    !=
verified
    !=
accepted
```

The code in this gate is the implementation baseline. Local/owner-host validation is the final acceptance authority.
