# Phase 10 — Security + Ecosystem

**Status:** COMPLETE  
**Closed:** 2026-09-18  
**Roadmap gates:** SEC-1, SEC-2, SEC-3, SDK-1, SDK-2, COMP-1, COMP-2

## Scope

Phase 10 closes the defensive security-intelligence layer and turns the existing plugin platform into a documented, machine-auditable extension contract.

### Security gates

- **SEC-1** — bounded suspicious-link/risk engine
- **SEC-2** — homoglyph/IDN analysis
- **SEC-3** — public defensive reputation adapters

### Ecosystem gates

- **SDK-1** — plugin capability metadata
- **SDK-2** — registry/compatibility tooling
- **COMP-1** — competitor feature matrix
- **COMP-2** — useful feature catch-up passes

## Security contract

The security layer is defensive only.

Allowed:
- URL/domain risk analysis;
- IDN/punycode/mixed-script inspection;
- bounded redirect observation through the existing public-intel service;
- public defensive reputation lookups;
- local hash reputation lookups;
- explainable risk scoring.

Not allowed:
- credential harvesting;
- password/token discovery;
- unauthorized active scanning;
- restriction circumvention;
- anti-ban behavior;
- storing secret values returned by public sources;
- treating visual similarity or a reputation hit as proof of identity or malicious intent.

### Risk semantics

LOW, MEDIUM, and HIGH are deterministic summaries of observable signals. They are not verdicts.

The engine records signals such as:
- HTTP instead of HTTPS;
- URL userinfo;
- literal IP host;
- punycode/IDN;
- mixed Unicode scripts;
- confusable characters;
- unusually long host/path/query;
- long redirect chains.

### Public adapters

- URL reputation: URLhaus public API.
- File-hash reputation: MalwareBazaar public API.

Provider responses are minimized before presentation. Raw provider payloads are not persisted by the security service.

### Commands

- .secrisk <url> — explainable bounded URL risk analysis.
- .idn <domain> — ASCII/Unicode/script/punycode/homoglyph inspection.
- .reputation <url|hash> — defensive public reputation lookup.

All commands remain ordinary deterministic text commands and use the existing command registry.

## Plugin SDK contract

Every plugin may declare:
- plugin_name
- plugin_version
- plugin_api_version
- plugin_description
- dependencies
- optional_dependencies
- capabilities
- critical

The runtime accepts legacy setup-only modules through deterministic compatibility defaults.

SDK_API_VERSION remains the public metadata compatibility version. The registry tool never imports plugin code.

## Registry tooling

tools/plugin_registry.py:
- scans plugin source using AST;
- emits a machine-readable registry;
- validates API compatibility;
- detects duplicate names;
- validates dependency references;
- never executes plugin code.

This complements, rather than replaces, PluginManager lifecycle ownership.

## Competitive matrix

See docs/COMPETITOR_FEATURE_MATRIX.md.

The matrix is an engineering gap audit, not a marketing ranking. Reference projects are used to identify useful feature families; their architecture is not copied.

## Acceptance

Phase 10 is closed. Owner-host acceptance evidence:
1. focused security tests pass;
2. registry tooling passes;
3. plugin ecosystem audit passes;
4. competitor matrix is frozen;
5. useful catch-up changes are implemented or explicitly marked as already covered;
6. full regression passes;
7. compileall passes;
8. production acceptance remains green;
9. system restart succeeds;
10. live .secrisk, .idn, and .reputation smoke tests succeed;
11. docs/state are updated with exact evidence.

### Closure evidence

- Focused Phase 10 security suite: **35 passed**.
- Plugin ecosystem quality audit: **PASS** (`PLUGIN_ECOSYSTEM_QUALITY_AUDIT_PASS`).
- Full regression: **352 passed**.
- Python `compileall`: **PASS**.
- Production acceptance: **10/10 automated gates PASS** (`PRODUCTION_ACCEPTANCE_PASS`).
- Owner-host `astra.service` restart: **PASS**; service returned `active (running)` and logged `SYSTEM READY`.
- Runtime after restart: **26/26 services**, **55 plugins RUNNING**, **150 commands**, **Jobs READY**, **BUBBLEWRAP-AVAILABLE**, **GROQ READY**.
- Live `.secrisk https://alokthakur.me`: **PASS**, LOW (0/100), no local heuristic risk signals.
- Live `.idn xn--80ak6aa92e.com`: **PASS**, Unicode `аррӏе.com`, mixed scripts, punycode and confusable detection all surfaced.
- Live `.reputation https://alokthakur.me`: **PASS**, LOW (0/100), URLhaus UNKNOWN, no local heuristic risk signals.
- Live reply-based `.secrisk` on `https://youtube.com`: **PASS**, one URL analyzed, LOW (0/100).

These live results validate the bounded defensive-only security commands in the actual Telegram runtime.
