# AstraUserbot 2.x — Competitive Completeness Addendum

**Purpose:** close the remaining product/ecosystem gaps identified during comparison against mature userbots such as CipherElite, CatUserbot, Hikka, Userge, Paperplane, UniBorg, Kaguya and Project Akasha.

This addendum is part of `ROADMAP.md`. It does **not** replace the roadmap or authorize an architecture rewrite. It adds five cross-cutting capabilities and adjusts implementation priorities.

---

## 1. Continuous Competitive Feature Matrix

`COMP-1` is promoted from a late-stage task into a **living repository artifact**.

Create a machine-readable and human-readable feature matrix that records:

```text
Capability
Competitor
Evidence/source
Astra implementation
Status
Quality level
Tests
Permissions
Network usage
Notes
```

Example status vocabulary:

- `MISSING`
- `PLANNED`
- `IMPLEMENTED`
- `VERIFIED`
- `DEPRECATED`
- `NOT_APPLICABLE`

The matrix must compare capabilities rather than marketing command counts.

### Required comparison families

- moderation;
- productivity;
- fun/general utilities;
- Telegram utilities;
- PM protection;
- media;
- search/inspection;
- inline UX;
- AI;
- automation;
- plugin architecture;
- plugin ecosystem;
- intelligence/OSINT;
- persistence;
- recovery;
- observability;
- security/isolation.

### Gate

`COMP-1` is complete only when each claimed competitive advantage has an auditable implementation or an explicit `PLANNED`/`NOT_APPLICABLE` status.

---

# 2. Command Bus / Command Contract

Astra needs a formal command abstraction above individual plugins.

Conceptual path:

```text
Telegram update
      ↓
Command Router
      ↓
Command Contract
      ↓
Authorization
      ↓
Execution Policy
      ↓
Plugin / Service
      ↓
JobEngine when durable
      ↓
Result / UX
```

Every command contract should be able to declare:

- canonical name;
- aliases;
- argument schema;
- usage/examples;
- category;
- permission requirements;
- operation class;
- priority;
- timeout/resource bounds;
- cancellation support;
- durable-execution support;
- network usage;
- destructive-effect classification;
- owning plugin/version.

The command bus must preserve the existing outgoing-only command ownership model and must not become a second event bus.

### Why

This gives Astra the foundation required for a large command surface without collisions, undocumented behavior or plugin-specific routing rules.

### Gates

- `CMD-1` command contract schema
- `CMD-2` router integration
- `CMD-3` permission/policy integration
- `CMD-4` command introspection
- `CMD-5` migration of representative existing commands

---

# 3. Command Discoverability System

Command discovery becomes a first-class product subsystem.

Target capabilities:

```text
.help
.help osint
.help .tgintel
.command search <text>
.command category <name>
.command describe <command>
.command examples <command>
.command aliases <command>
.command permissions <command>
.command source <command>
```

Each command's discoverable record should expose, where appropriate:

- description;
- syntax;
- examples;
- aliases;
- permissions;
- network behavior;
- operation class;
- whether it starts a durable job;
- whether it can mutate Telegram state;
- owning plugin.

Discovery output must be paginated and Telegram-friendly.

### Gate

`UX-CMD-1` — unified command discovery backed by the command contract registry.

---

# 4. Unified Search Plane

Astra already has SQLite/FTS5, archive, events, media metadata and intelligence records. They should become one searchable product surface.

Target interface:

```text
.search <query>
```

or an equivalent canonical command selected during implementation.

The search plane should be able to query, within explicit scope:

- Telegram messages;
- archived messages;
- media metadata;
- OCR text;
- transcripts;
- entities;
- IOCs;
- domains;
- cases;
- events;
- plugin metadata;
- intelligence observations.

Example conceptual result:

```text
example.com

Telegram
  41 messages

Media
  7 images
  2 screenshots

IOC
  domain: example.com

Infrastructure
  4 IP observations
  12 certificate observations

Cases
  CASE-0042
```

Search results must retain provenance and timestamps and must distinguish exact matches from derived/correlated matches.

### Gates

- `SEARCH-1` unified index contract
- `SEARCH-2` cross-domain adapters
- `SEARCH-3` ranked/bounded result aggregation
- `SEARCH-4` Telegram UX/pagination

---

# 5. Unified Entity Inspector

Create one intelligence front door rather than requiring users to know which subsystem owns a target.

Target:

```text
.inspect <target>
```

Examples:

```text
.inspect @username
.inspect example.com
.inspect 1.2.3.4
.inspect https://example.com
.inspect <message>
.inspect <media>
```

The inspector should:

1. classify/normalize the target;
2. identify relevant intelligence engines;
3. retrieve bounded local observations;
4. optionally perform permitted public-source enrichment;
5. correlate evidence;
6. produce a concise summary;
7. provide drill-down actions into the underlying records.

It must never silently turn a weak correlation into an identity assertion.

### Gates

- `INSPECT-1` target classifier
- `INSPECT-2` engine dispatch
- `INSPECT-3` evidence summary
- `INSPECT-4` drill-down UX

---

# 6. Explicit Intelligence Correlation Engine

IntelGraph is the storage/foundation layer. **Correlation is a separate execution capability.**

Conceptual pipeline:

```text
Telegram
IOC
Domain
Git
Media
OCR
STT
Public web
   ↓
Normalization
   ↓
Entity resolution
   ↓
Relationship inference
   ↓
Evidence scoring
   ↓
Contradiction detection
   ↓
Timeline projection
   ↓
Case/report projection
```

The correlation engine must distinguish:

- direct observation;
- normalized equivalence;
- inferred relationship;
- corroborated relationship;
- contradiction;
- unresolved ambiguity.

Every derived relationship must retain:

- supporting observation IDs;
- source IDs;
- timestamps;
- scoring/reason codes;
- confidence;
- contradiction state.

### Important rule

Confidence is evidence-weighted, not identity certainty. A username match alone must never become a definitive identity claim.

### Gates

- `CORR-1` correlation input contract
- `CORR-2` entity resolution
- `CORR-3` evidence scoring
- `CORR-4` contradiction detection
- `CORR-5` graph/timeline integration

---

# 7. Plugin Compatibility API

The plugin ecosystem needs a stable compatibility layer so external plugins do not depend on Astra internals.

Target conceptual API:

```text
AstraPlugin API v1
        │
        ├── Telegram
        ├── Storage
        ├── HTTP
        ├── Jobs
        ├── Media
        ├── AI
        ├── Search
        ├── Intelligence
        └── UI
```

Plugins should consume capabilities through stable service contracts rather than importing implementation internals.

Plugin compatibility metadata should include:

- API version;
- minimum Astra version;
- maximum tested Astra version;
- required services;
- required capabilities;
- permissions;
- migrations;
- compatibility status.

### Gates

- `SDK-1` stable service capability interfaces
- `SDK-2` API versioning
- `SDK-3` compatibility validation
- `SDK-4` example/reference plugin
- `SDK-5` quarantine/incompatibility handling

### Ecosystem reality

A mature SDK and registry can make a large ecosystem possible, but cannot guarantee third-party adoption. Therefore ecosystem size must remain an observed metric, not a promised feature claim.

---

# 8. Astra Control Plane

This is a **conceptual in-process control plane**, not a new microservice.

It unifies operator visibility over:

```text
                 ASTRA CONTROL PLANE
                        │
 ┌──────────────┬───────┼───────┬──────────────┐
 ▼              ▼       ▼       ▼              ▼
Plugins        Jobs   Telegram  Intel         Media
              │       │         │              │
              └───────┴─────────┴──────────────┘
                            │
                         SQLite/WAL
```

Existing operator surfaces remain, but should converge on one control-plane model:

```text
.status
.health
.jobs
.plugins
.telegram
.intel
.media
.storage
```

The control plane owns **observation and coordination**, not a second storage authority.

### Gates

- `CTRL-1` control-plane state model
- `CTRL-2` operator projections
- `CTRL-3` cross-system diagnostics
- `CTRL-4` health/readiness aggregation

---

# 9. Revised implementation dependency order

The original roadmap order remains valid, but the dependency graph is improved by moving the intelligence foundation earlier.

Recommended high-level order:

```text
Phase 1  Telegram Core
Phase 2  Telegram State
Phase 3  Telegram Events
Phase 4  Intelligence Foundation
Phase 5  Archive
Phase 6  Command Bus + UX foundation
Phase 7  Automation
Phase 8  Product feature expansion
Phase 9  AI Product 2.0
Phase 10 Intelligence sources
Phase 11 Media intelligence + Cases
Phase 12 Security intelligence
Phase 13 Plugin ecosystem
Phase 14 Competitive catch-up / final parity
Phase 15 Release + operations hardening
```

### Why intelligence moves earlier

The natural dependency chain is:

```text
Telegram Events
      ↓
Observation Model
      ↓
IntelGraph / IOC
      ↓
Timeline
      ↓
Archive / Media / AI / Public Sources
      ↓
Correlation
      ↓
Cases / Reports
```

The earlier phase should establish only the **schema, contracts and minimal foundation**. It must not delay Telegram Core or turn the project into an OSINT-only product.

---

# 10. Competitive target clarification

The Astra target should be represented honestly.

| Capability | Target |
|---|---|
| Telegram administration | ★★★★★ |
| Plugin architecture | ★★★★★ |
| AI integration | ★★★★★ |
| AI as infrastructure | ★★★★★ |
| Persistent local state | ★★★★★ |
| SQLite/FTS intelligence | ★★★★★ |
| Durable jobs/workflows | ★★★★★ |
| Crash recovery | ★★★★★ |
| Retry/failure semantics | ★★★★★ |
| Telegram traffic governance | ★★★★★ |
| Security architecture | ★★★★★ |
| Media intelligence | ★★★★★ |
| OCR/STT pipeline | ★★★★★ |
| OSINT | ★★★★★ |
| IOC intelligence | ★★★★★ |
| Entity graph | ★★★★★ |
| Telegram relationship graph | ★★★★★ |
| Timeline intelligence | ★★★★★ |
| Case management | ★★★★★ |
| Evidence/provenance | ★★★★★ |
| Content-addressed media | ★★★★★ |
| Perceptual media correlation | ★★★★★ |
| Observability | ★★★★★ |
| Offline/local-first | ★★★★★ |
| Architecture correctness | ★★★★★ |
| Zero-cost/local AI | ★★★★★ |
| Command discoverability | ★★★★★ |
| Unified search | ★★★★★ |
| Unified entity inspection | ★★★★★ |
| Correlation engine | ★★★★★ |
| Plugin compatibility API | ★★★★★ |
| Huge plugin ecosystem | ★★★★☆ |
| Third-party ecosystem size | ★★★★☆ |
| Fun/general command breadth | ★★★★☆ |

The last three are deliberately not promised as five-star outcomes because ecosystem size and community adoption are not fully controllable by engineering.

---

# 11. New cross-cutting completion rule

A new command or plugin is not considered product-complete merely because it executes successfully.

It should be represented, where applicable, in:

```text
Command Contract
      ↓
Permission / Safety
      ↓
Traffic Policy
      ↓
Plugin / Service
      ↓
Job / Event / Search / Intel projection
      ↓
Unified Discovery
      ↓
Tests + Production Acceptance
```

Not every command needs every projection, but every command must explicitly declare which contracts apply.

---

# 12. What this addendum deliberately does not change

It does not change:

- Telethon as transport;
- SQLite/WAL as durable source of truth;
- existing JobEngine;
- existing service architecture;
- Bubblewrap isolation;
- zero-cost constraint;
- AI advisory authority model;
- public/legitimately observable intelligence boundary;
- anti-ban/evasion prohibition;
- no Redis/Kafka/Celery/Kubernetes/microservice rewrite.

The objective is **competitive completeness without architectural regression**.
