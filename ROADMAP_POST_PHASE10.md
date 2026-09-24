# AstraUserbot — Post-Phase-10 Master Execution Roadmap

**Status:** Active execution baseline  
**Current repository checkpoint:** Phase 10 accepted; post-Phase-10 maturity/integration work is next  
**Current HEAD:** `037b3625b08bc1598cabce5dd43cc019dc74be27`  
**Architecture:** single-process Python/asyncio modular monolith  
**Transport:** Telethon  
**Durable store:** SQLite/WAL  
**Cost ceiling:** ₹0 / $0  
**Execution rule:** prerequisite-first, evidence-first, no hidden completion

> This document is the **post-Phase-10 execution plan**. It does not delete, replace, or invalidate any existing roadmap item. `ROADMAP.md` remains the complete historical/capability roadmap; `ROADMAP_COMPETITIVE_ADDENDUM.md` remains the competitive/product-surface addendum. This file reconciles both with the **actual implementation state** and defines the order in which the remaining work must now be built and accepted.

---

# 1. Why this roadmap exists

The repository has completed the original numbered execution sequence through **Phase 10**:

1. Telegram/core foundation — complete
2. Telegram state/events — complete
3. archive + UX foundation — complete
4. product expansion — complete
5. AI Product 2.0 foundation — complete
6. automation engine — complete
7. IntelGraph + IOC foundation — complete
8. public-source intelligence — complete
9. media intelligence + investigation/cases — complete
10. security intelligence + plugin ecosystem + competitive catch-up — complete

The old competitive addendum contains a proposed Phase 1–15 ordering, but that ordering is now **historical/proposed dependency architecture**, not a reason to start a new “Phase 11.”

The actual repository state is more advanced than that numbering suggests.

Therefore the next work is a **post-Phase-10 maturity/integration program**.

The goal is to connect the already-built subsystems into a coherent product:

```
Command Contract
      ↓
Discovery
      ↓
Unified Search
      ↓
Entity Inspector
      ↓
Correlation
      ↓
Evidence
      ↓
Timeline / Case
      ↓
AI explanation / report
      ↓
Operator control / recovery
```

The remaining work is therefore primarily about **contracts, integration, discoverability, unified UX, and product maturity**, not about inventing duplicate engines.

---

# 2. Non-negotiable invariants

Every gate below must preserve these constraints.

## 2.1 Architecture

Keep:

- Python + asyncio;
- Telethon as Telegram transport;
- SQLite/WAL as durable source of truth;
- `ApplicationContext`;
- `TaskSupervisor` for ephemeral tasks;
- `JobEngine` for restart-sensitive/durable work;
- existing Telegram facade/traffic controller;
- existing Media service;
- existing Search service;
- existing AI gateway;
- existing Isolation service;
- existing IntelGraph;
- existing IOC/intelligence services;
- plugin-first delivery;
- Bubblewrap isolation where required.

Do **not** introduce:

- Redis;
- Kafka;
- Celery;
- Kubernetes;
- microservices;
- a second workflow engine;
- a second event bus;
- a second storage authority.

## 2.2 Cost

All work remains genuinely zero-cost:

- no paid API requirement;
- no paid hosting;
- no mandatory SaaS;
- no mandatory hosted database;
- no pay-per-use architecture;
- no provider lock-in;
- local/free AI providers remain replaceable adapters.

## 2.3 Safety

Allowed intelligence scope:

- public information;
- legitimately observable Telegram information;
- authorized owner assets;
- defensive analysis;
- local evidence already collected by Astra.

Never turn the roadmap into:

- anti-ban/evasion;
- account rotation;
- fake-client/fingerprint spoofing;
- FloodWait bypass;
- credential harvesting;
- secret recovery/storage;
- unauthorized active scanning;
- invasive surveillance;
- unsupported identity assertions.

## 2.4 Authority

AI is advisory.

AI may:

- summarize;
- explain;
- classify;
- extract;
- correlate;
- propose;
- draft.

AI may not become:

- authorization;
- durable truth;
- direct Telegram mutation authority;
- permission bypass;
- safety-policy bypass.

All real mutations continue through deterministic authorization, policy and Telegram traffic-control layers.

---

# 3. Global completion contract

A gate is **COMPLETE** only when all applicable evidence exists.

### Required evidence

1. design/architecture recorded;
2. current implementation inspected;
3. prerequisites verified;
4. migrations defined/tested when required;
5. implementation complete;
6. unit tests;
7. integration/contract tests;
8. failure-path tests;
9. cancellation behavior;
10. resource bounds;
11. authorization/safety boundaries;
12. diagnostics/observability;
13. documentation;
14. production acceptance;
15. owner-host/live validation where relevant;
16. full regression remains green;
17. no duplicate subsystem or hidden authority introduced.

### Status vocabulary

Use only:

- `DESIGNED`
- `BLOCKED`
- `IN_PROGRESS`
- `IMPLEMENTED`
- `VERIFIED`
- `ACCEPTED`
- `DEFERRED`
- `NOT_APPLICABLE`

Do not call a feature complete merely because:

- code exists;
- a command appears in help;
- an isolated test passes;
- documentation exists;
- a dataset was found;
- a repository was forked;
- an adapter was written.

---

# 4. Current implementation baseline

The following are already real and must be **reused**, not rebuilt.

## 4.1 Platform

Implemented:

- ApplicationContext;
- TaskSupervisor;
- durable JobEngine;
- SQLite/WAL storage;
- Telegram facade/traffic control;
- media service;
- search service;
- AI gateway;
- isolation service;
- plugin lifecycle;
- diagnostics/recovery.

## 4.2 Telegram

Implemented:

- Telegram state/cache;
- capability observations;
- incremental synchronization;
- durable event journal/projections/replay;
- archive jobs;
- FTS5 search;
- resumable JobEngine execution.

## 4.3 Automation

Implemented and accepted:

- durable rules;
- triggers/scopes/matching;
- action execution;
- durable automation runs;
- idempotency;
- reconciliation;
- stale rule-version rejection;
- JobEngine integration;
- recovery/audit.

## 4.4 Intelligence

Implemented:

- IntelGraph;
- IntelCorrelationEngine;
- IOC extraction/normalization;
- public-source intelligence;
- Telegram intelligence;
- identity/username intelligence;
- domain/infrastructure intelligence;
- link intelligence;
- media intelligence;
- investigation/cases;
- timeline foundations;
- security intelligence.

Important: the **correlation engine already exists**. Future work exposes, strengthens and integrates it; it must not create a competing correlation engine.

## 4.5 Security

Accepted:

- suspicious URL/risk analysis;
- IDN/punycode;
- homoglyph/confusable detection;
- redirect analysis;
- URLhaus;
- MalwareBazaar hash reputation;
- bounded message URL analysis.

## 4.6 Plugin ecosystem

Accepted foundation:

- capability metadata;
- AST registry/compatibility inspection;
- dependency/conflict validation;
- plugin ecosystem audit;
- plugin detail/overview surfaces.

Remaining work is primarily the **user-facing ecosystem experience and stable compatibility surface**, not the basic registry.

## 4.7 AI

Accepted foundation:

- provider-independent gateway;
- Groq;
- Gemini;
- local Ollama;
- bounded input/output;
- timeout/concurrency controls;
- fallback configuration;
- remote request limits;
- transcription where supported;
- durable AI jobs.

Remaining work is product UX and integration, not another AI backend.

## 4.8 Production baseline

Phase 10 evidence includes:

- full regression: 352 passed;
- compileall PASS;
- plugin behavior audit PASS;
- plugin ecosystem audit PASS;
- media pipeline audit PASS;
- isolation security audit PASS;
- storage hardening audit PASS;
- job hardening audit PASS;
- production acceptance PASS;
- systemd restart PASS;
- live security smoke tests PASS;
- 55 active plugins;
- 150 commands;
- Jobs READY;
- Bubblewrap available;
- AI Gateway ready;
- system READY.

Future work must preserve this baseline.

---

# 5. Master execution order

The remaining program is:

```
GATE A  Command Contract + Discoverability
   ↓
GATE B  Unified Search Plane
   ↓
GATE C  Unified Entity Inspector
   ↓
GATE D  Correlation / Intelligence UX
   ↓
GATE E  Interactive UX Maturity
   ↓
GATE F  Plugin UX + Compatibility
   ↓
GATE G  AI Product UX
   ↓
GATE H  Astra Control Plane / Operator UX
   ↓
PRODUCT MATURITY GATE
   ↓
DATASET / HUGGING FACE RESEARCH TRACK
   ↓
REMAINING INTELLIGENCE / MEDIA / RELEASE HARDENING
   ↓
FINAL RELEASE ACCEPTANCE
```

The dataset track is intentionally separate because its prerequisites are external-source and lineage research rather than ordinary feature implementation.

---

# 6. GATE A — Command Contract + Discoverability

**Objective:** turn the existing command registry into the authoritative, mature command system.

**Priority:** FIRST.

## A.0 Prerequisites

Before implementation:

1. inspect the actual command registry;
2. inspect every command metadata shape currently used;
3. inventory all command registrations;
4. inventory aliases;
5. detect duplicate canonical names;
6. detect duplicate aliases;
7. identify commands without metadata;
8. identify commands with inconsistent metadata;
9. inspect existing `.help`, search and plugin discovery;
10. inspect command permission handling;
11. inspect destructive/mutation classifications;
12. inspect durable job integration;
13. inspect relevant tests;
14. preserve existing command behavior unless the contract requires a safety correction.

No registry rewrite should happen before this census.

## A.1 Command contract

Every production command should have a canonical record containing, where applicable:

- canonical command name;
- aliases;
- plugin owner;
- plugin version;
- category;
- description;
- usage;
- argument schema;
- examples;
- permission requirements;
- operation class;
- priority;
- network usage;
- durable-job behavior;
- cancellation support;
- resource limits;
- destructive/mutation classification;
- confirmation requirement;
- compatibility/API version;
- source/implementation reference.

### Operation classes

At minimum:

- READ;
- NETWORK;
- MUTATION;
- DESTRUCTIVE;
- JOB.

Existing richer classifications may be preserved where they add value.

## A.2 Canonical identity

Rules:

- one canonical name;
- aliases are metadata, not hidden alternate registrations;
- alias collisions are rejected deterministically;
- command ownership is explicit;
- plugin load order must not change command meaning;
- no command may silently shadow another command.

## A.3 Permission contract

Every command must make its authorization expectations explicit.

Examples:

- owner-only;
- admin/moderator;
- chat permission;
- public/read-only;
- explicit capability required.

Permission metadata must never bypass existing runtime authorization.

## A.4 Discovery

Implement a unified discovery layer backed by the same registry.

Target surfaces:

```
.help
.help <category>
.command search <query>
.command category <name>
.command describe <command>
.command examples <command>
.command aliases <command>
.command permissions <command>
.command source <command>
```

The exact public syntax may be normalized to existing conventions to avoid collisions.

## A.5 Privacy-safe recent commands

If recent-command discovery is implemented:

- do not persist sensitive arguments;
- do not expose secrets/tokens/URLs containing credentials;
- store command identity rather than raw private payload;
- make retention bounded;
- keep it owner-scoped.

## A.6 Acceptance tests

Must prove:

- canonical identity;
- alias resolution;
- alias collision rejection;
- deterministic conflict handling;
- metadata completeness;
- permission metadata;
- operation class;
- network/mutation/job metadata;
- command search;
- category search;
- description;
- examples;
- source;
- pagination;
- privacy-safe recent history;
- compatibility with representative legacy commands.

## A.7 Gate exit

`GATE-A-ACCEPTED` only after:

- representative commands migrated;
- all production commands are registry-visible;
- registry conflict audit passes;
- focused command tests pass;
- full regression passes;
- help/discovery smoke test passes;
- documentation updated.

---

# 7. GATE B — Unified Search Plane

**Objective:** turn the existing FTS5/SearchService into one product-level search front door.

## B.0 Prerequisites

Verify first:

- SearchService API;
- existing FTS5 schema;
- archive tables;
- event/projection tables;
- media metadata;
- OCR/transcript storage;
- IntelGraph entities/observations;
- IOC storage;
- case storage;
- security evidence;
- plugin metadata;
- command registry;
- permissions/visibility rules.

Do not create a parallel search database unless the existing architecture proves incapable.

## B.1 Search domains

Unify search over:

- commands;
- plugins;
- Telegram archive;
- messages;
- media;
- OCR;
- transcripts;
- intelligence entities;
- IOCs;
- domains;
- cases;
- events;
- security evidence;
- observations.

## B.2 Unified result contract

Every result should expose, where applicable:

- stable result ID;
- result type;
- title/label;
- short preview;
- timestamp;
- source;
- source link/reference;
- evidence IDs;
- entity IDs;
- confidence/derivation state;
- owning subsystem;
- permission visibility;
- drill-down action.

## B.3 Ranking

Ranking must be deterministic and bounded.

Suggested signals:

1. exact canonical match;
2. exact normalized match;
3. prefix match;
4. token match;
5. source/type relevance;
6. recency;
7. evidence strength.

Do not let correlation outrank an exact source match merely because it is “interesting.”

## B.4 Filters

Support bounded filters:

- type;
- source;
- time range;
- chat;
- plugin;
- case;
- intelligence domain;
- exact/derived.

## B.5 Pagination

Search must support:

- deterministic ordering;
- stable page cursor;
- bounded page size;
- no duplicate results across pages;
- safe cancellation.

## B.6 Permission-aware search

Search must not become a data-leak surface.

Before returning a result:

- verify owner scope;
- verify chat/archive scope;
- verify plugin/operator scope;
- verify case visibility;
- verify sensitive evidence policy.

## B.7 Acceptance

Must prove:

- one front door;
- cross-domain aggregation;
- ranking;
- filtering;
- stable IDs;
- pagination;
- provenance;
- permission filtering;
- no duplicate index authority;
- bounded query cost.

---

# 8. GATE C — Unified Entity Inspector

**Objective:** create the missing common `.inspect` layer.

## C.0 Prerequisites

Before implementation, inventory existing target resolvers for:

- URL;
- domain;
- IP;
- username;
- Telegram user;
- Telegram chat;
- message;
- IOC;
- media;
- case;
- plugin;
- command.

Do not reimplement individual intelligence engines.

## C.1 Target classifier

Normalize a target into a typed target:

```
URL
DOMAIN
IP
USERNAME
TELEGRAM_USER
TELEGRAM_CHAT
MESSAGE
IOC
MEDIA
CASE
PLUGIN
COMMAND
UNKNOWN
```

Classification must be deterministic and bounded.

## C.2 Engine dispatch

Map target types to existing services:

- URL → link/security intelligence;
- domain → domain/infrastructure intelligence;
- IP → infrastructure/IOC;
- username → identity/Telegram intelligence;
- Telegram entity → Telegram intelligence/state;
- message → archive/event/IOC/media;
- IOC → IOC service;
- media → media intelligence;
- case → case/timeline;
- plugin → plugin registry;
- command → command registry.

## C.3 Inspector result contract

Every inspector result should separate:

### Observed

Facts directly supported by evidence.

### Derived

Relationships derived from multiple observations.

### Possible

Signals requiring further validation.

### Contradiction

Evidence that conflicts.

### Unknown

Information not available.

Never collapse these into one “truth” field.

## C.4 Drill-down

Inspector should link to:

- evidence;
- source;
- relationship;
- timeline;
- case;
- search;
- relevant command;
- available safe actions.

## C.5 Acceptance

Must prove all supported target types resolve through one front door and that no weak correlation becomes an identity assertion.

---

# 9. GATE D — Correlation / Intelligence UX

**Objective:** expose the existing `IntelCorrelationEngine` through the product spine.

## D.0 Prerequisites

Verify:

- correlation engine implementation;
- IntelGraph entity model;
- observation/source model;
- relationship model;
- confidence semantics;
- contradiction handling;
- timeline projection;
- case integration;
- evidence references.

No second correlation engine.

## D.1 Correlation flow

```
search
  ↓
inspect
  ↓
correlate
  ↓
evidence
  ↓
timeline
  ↓
case
```

## D.2 Correlation contract

Every derived relationship retains:

- supporting observation IDs;
- source IDs;
- timestamps;
- reason codes;
- score/confidence;
- contradiction state;
- derivation type.

## D.3 Explicit evidence classes

At minimum:

- observed fact;
- normalized equivalence;
- derived relationship;
- corroborated relationship;
- contradiction;
- unresolved ambiguity.

## D.4 Operator UX

Expose:

- why a relationship exists;
- which evidence supports it;
- what evidence conflicts;
- what is unknown;
- how to drill down.

## D.5 Acceptance

Must prove correlation is explainable, reproducible, bounded and evidence-linked.

---

# 10. GATE E — Interactive UX Maturity

**Objective:** make existing UX primitives coherent and reusable.

This is a **platform primitive gate**, not a command-by-command UI rewrite.

## E.0 Existing assets to reuse

Inspect and reuse:

- inline buttons;
- callback handling;
- pagination;
- progress;
- HUD;
- structured errors;
- job controls;
- cancellation;
- confirmation patterns.

## E.1 UX primitives

Standardize:

- buttons;
- menus;
- lists;
- forms;
- galleries;
- pagination;
- progress;
- cancellation;
- confirmation;
- retry;
- navigation;
- source/evidence drill-down.

## E.2 Callback contract

Callbacks must be:

- namespaced;
- validated;
- authorization-aware;
- bounded;
- expiry-aware where appropriate;
- safe against stale UI actions;
- compatible with durable job IDs/entity IDs.

## E.3 Forms

Forms should cover high-value workflows such as:

- automation creation;
- archive scope;
- AI context selection;
- case creation;
- source inspection;
- moderation configuration.

Forms must resolve to the same Command Contract as text commands.

## E.4 Galleries

Bound:

- result count;
- media size;
- concurrent fetches;
- storage;
- lifetime.

Use for:

- media;
- screenshots;
- archive media;
- evidence.

## E.5 Lists

Use shared list UX for:

- plugins;
- commands;
- cases;
- jobs;
- sources;
- entities;
- evidence.

## E.6 Progress

Standard lifecycle:

```
QUEUED
RUNNING
WAITING
COMPLETED
FAILED
RECOVERY_REQUIRED
CANCELLED
```

## E.7 Structured errors

Every user-facing failure should answer:

1. what failed;
2. whether anything changed;
3. whether retry is safe;
4. what the user can do next;
5. where diagnostics are available.

## E.8 Acceptance

Migrate high-value workflows only:

- search;
- inspect;
- jobs;
- cases;
- plugins;
- moderation;
- AI.

Do not waste time converting every trivial command.

---

# 11. GATE F — Plugin UX + Compatibility

**Objective:** finish the user-facing plugin ecosystem without weakening isolation or lifecycle safety.

## F.0 Prerequisites

Verify:

- current plugin registry;
- lifecycle manager;
- plugin metadata;
- dependency/conflict checks;
- quarantine;
- health checks;
- compatibility tooling;
- active job behavior;
- plugin source/version metadata.

## F.1 Stable plugin contract

Define a stable API surface:

```
AstraPlugin API v1
  ├─ Telegram
  ├─ Storage
  ├─ HTTP
  ├─ Jobs
  ├─ Media
  ├─ AI
  ├─ Search
  ├─ Intelligence
  └─ UI
```

Plugin metadata:

- API version;
- minimum Astra;
- maximum tested Astra;
- required services;
- required capabilities;
- permissions;
- migrations;
- compatibility status.

## F.2 Plugin catalog

`.plugins` should expose:

- installed;
- running;
- disabled;
- quarantined;
- incompatible;
- version;
- capabilities;
- commands;
- dependencies;
- network access;
- permissions;
- source.

## F.3 Plugin detail

`.plugin <name>` should expose:

- purpose;
- commands;
- aliases;
- services;
- permissions;
- network usage;
- durable jobs;
- configuration;
- dependencies;
- compatibility;
- source;
- version;
- safety classification;
- lifecycle state;
- health.

## F.4 Lifecycle

Provide controlled operations:

- enable;
- disable;
- reload where safe;
- quarantine;
- update;
- rollback;
- compatibility validation;
- health.

Lifecycle operations must not corrupt active jobs or durable state.

## F.5 Safe installation

Required workflow:

```
discover
→ inspect
→ compatibility check
→ dependency check
→ policy check
→ install
→ load
→ health check
→ enable
```

Never implement blind dependency installation.

## F.6 Acceptance

Must prove:

- API compatibility;
- dependency conflict detection;
- quarantine;
- lifecycle safety;
- active-job safety;
- plugin UX;
- source/version visibility.

---

# 12. GATE G — AI Product UX

**Objective:** make the existing AI gateway feel native to Astra.

## G.0 Prerequisites

Verify:

- AI gateway;
- provider adapters;
- context limits;
- durable AI jobs;
- transcription;
- media service;
- search;
- evidence;
- cases;
- permissions.

## G.1 Core AI flows

Implement as thin product adapters:

```
reply → AI
message → summarize
message → explain
media → OCR/STT → AI
search → AI synthesis
evidence → explanation
case → report draft
timeline → summary
```

## G.2 Context builder

Context sources may include:

- replied message;
- bounded message window;
- archive results;
- OCR;
- transcript;
- intelligence observations;
- case timeline.

Context must be:

- bounded;
- source-aware;
- privacy-conscious;
- reproducible;
- size-limited.

## G.3 Structured AI output

Where practical, use structured internal results containing:

- answer;
- sources;
- evidence references;
- confidence/limitations;
- provider/model;
- timestamp;
- job ID where durable.

## G.4 AI failure handling

Expose:

- provider status;
- timeout;
- retry safety;
- fallback;
- malformed output;
- cancellation;
- job state.

## G.5 Mutation boundary

AI output cannot directly mutate Telegram.

Required flow:

```
AI proposal
→ deterministic policy
→ authorization
→ command/action contract
→ TelegramTrafficController
→ result
```

## G.6 Acceptance

Must prove reply-based AI, bounded context, media AI, search synthesis and evidence/case assistance without silent mutation.

---

# 13. GATE H — Astra Control Plane / Operator UX

**Objective:** converge operator visibility into one in-process control-plane model.

This is **not a microservice**.

## H.0 Operator surfaces

Converge existing capabilities into:

```
.status
.health
.doctor
.jobs
.plugins
.telegram
.intel
.media
.storage
.config
.update
.restart
```

## H.1 Health model

Aggregate:

- service health;
- plugin health;
- job health;
- Telegram traffic state;
- storage state;
- search/index state;
- AI provider state;
- isolation state;
- recovery state.

## H.2 Doctor

`.doctor` should identify:

- configuration problems;
- dependency problems;
- storage issues;
- migration issues;
- plugin incompatibilities;
- job/recovery anomalies;
- search/index problems;
- AI provider problems;
- isolation availability.

Diagnostics must be safe and redact secrets.

## H.3 Jobs

`.jobs` should expose:

- queued;
- running;
- waiting;
- completed;
- failed;
- cancelled;
- recovery required;
- retryable;
- non-retryable.

## H.4 Update

`.update` should:

- show current version;
- check available update;
- preflight compatibility;
- preserve configuration;
- preserve durable state;
- refuse unsafe migration;
- expose rollback/recovery;
- verify post-update health.

## H.5 Restart

`.restart` must be explicit, observable and compatible with systemd/lifecycle semantics.

## H.6 Acceptance

Control-plane diagnostics must provide one coherent operator view without becoming a second authority over jobs/storage/events.

---

# 14. PRODUCT MATURITY GATE

After A–H, perform a full product maturity review.

## PM-1 Command maturity

- all commands have contract metadata;
- discoverability works;
- aliases are explicit;
- permissions are visible;
- mutation/network/job behavior is visible.

## PM-2 Search maturity

- one search front door;
- cross-domain results;
- stable IDs;
- provenance;
- filtering;
- pagination;
- permission awareness.

## PM-3 Inspection maturity

- one `.inspect` front door;
- all supported target types;
- evidence;
- relationships;
- confidence;
- contradictions;
- timestamps.

## PM-4 Correlation maturity

- explainable;
- evidence-linked;
- contradiction-aware;
- no unsupported identity claims.

## PM-5 UX maturity

- buttons;
- pagination;
- forms;
- lists;
- galleries;
- progress;
- cancellation;
- confirmations;
- structured errors.

## PM-6 Plugin maturity

- catalog;
- detail;
- lifecycle;
- compatibility;
- safe installation.

## PM-7 AI maturity

- reply;
- summarize;
- explain;
- media;
- search;
- evidence;
- case/timeline;
- bounded context.

## PM-8 Operator maturity

- status;
- health;
- doctor;
- jobs;
- plugins;
- storage;
- AI;
- isolation;
- recovery;
- update/restart.

## PM-9 Product acceptance

Require:

- focused tests for every gate;
- full regression;
- compileall;
- production acceptance;
- systemd restart;
- live owner-host smoke tests;
- documentation;
- no architecture regressions.

---

# 15. DATASET / HUGGING FACE RESEARCH TRACK

**Do not implement this track before its research prerequisites are satisfied.**

The existence of a dataset repository is not evidence that it is the authoritative source.

## DS-0 — Account census

Before dataset selection:

1. enumerate relevant Hugging Face accounts/organizations;
2. identify owner accounts;
3. identify mirrors;
4. identify forks;
5. identify community accounts;
6. identify organizations publishing related families;
7. record evidence for account relationships.

**Exit:** account census artifact exists.

## DS-1 — Dataset inventory

For every relevant dataset:

- owner;
- repository;
- title;
- description;
- size;
- modality;
- language;
- license;
- creation/update history;
- files;
- revisions;
- tags;
- linked paper/project;
- source links.

**Exit:** machine-readable inventory.

## DS-2 — Family clustering

Cluster repositories into families based on:

- names;
- metadata;
- file structure;
- revision history;
- dataset cards;
- README references;
- author overlap;
- upstream references.

**Exit:** every candidate belongs to a family or is explicitly unclassified.

## DS-3 — Lineage comparison

Determine:

- original;
- fork;
- mirror;
- subset;
- merged dataset;
- derived dataset;
- transformed dataset;
- cleaned/reformatted dataset;
- unknown lineage.

Compare:

- hashes where possible;
- file names;
- row/sample counts;
- schema;
- metadata;
- revision history;
- source references.

**Exit:** lineage table with evidence.

## DS-4 — Duplicate/derived detection

Do not count:

- mirrors;
- forks;
- subsets;
- transformed copies;
- merged copies

as independent sources.

**Exit:** unique-source count.

## DS-5 — Master candidate

Select candidate authoritative source(s) using explicit evidence:

- owner provenance;
- upstream references;
- revision history;
- completeness;
- uniqueness;
- project linkage;
- license;
- maintenance;
- reproducibility.

Never select a master merely because it has the most stars/downloads.

## DS-6 — Unique coverage

Measure what each family/source contributes uniquely.

**Exit:** unique-coverage report.

## DS-7 — Source manifest

Create a manifest recording:

- canonical source;
- mirrors;
- forks;
- subsets;
- derived datasets;
- lineage evidence;
- retrieval metadata;
- revision;
- license;
- provenance.

## DS-8 — Remote query validation

Before downloading large data:

- test metadata endpoints;
- test small remote queries;
- verify revisions;
- verify access;
- verify expected schema;
- verify availability.

## DS-9 — Provenance

Every imported dataset record must retain:

- source;
- owner;
- revision;
- retrieval timestamp;
- lineage;
- transformation;
- checksum where feasible;
- license;
- import job ID.

## DS-10 — Graph ingestion

Only after DS-0 through DS-9:

```
dataset
→ source
→ lineage family
→ entities
→ observations
→ provenance
→ IntelGraph
```

## HF acceptance

Only then may `HF-1..HF-7` implementation gates be opened.

Never:

- fork random datasets;
- build adapters for every fork;
- download huge datasets casually;
- claim a master without evidence;
- treat duplicate datasets as independent corroboration.

---

# 16. Remaining intelligence adapters after product maturity

After the product spine is complete, audit the A–T capability map against actual code.

Remaining work may include:

- additional public-source adapters;
- identity/username source expansion;
- domain/infrastructure adapters;
- link intelligence expansion;
- Git/public-code intelligence;
- media-source adapters;
- additional IOC enrichments;
- evidence fusion;
- timeline projections;
- case/report projections.

Every adapter must follow:

```
source
→ acquisition
→ normalization
→ observation
→ provenance
→ IntelGraph/search
→ correlation
```

No adapter may write identity claims directly.

---

# 17. Remaining media maturity

Audit and complete practical media workflows:

- media inspection;
- conversion;
- compression;
- metadata;
- screenshot/frame extraction;
- OCR;
- STT;
- TTS where available locally/free;
- hashes;
- perceptual correlation;
- deduplication;
- archive/export;
- evidence attachment;
- media search;
- case integration.

Reuse the existing media intelligence pipeline.

No second media engine.

---

# 18. Release / Operations hardening

This is the final release track after product maturity.

## R1 Documentation

Keep synchronized:

- `ROADMAP.md`;
- this file;
- `ROADMAP_COMPETITIVE_ADDENDUM.md`;
- architecture docs;
- safety contract;
- data model;
- UX docs;
- intelligence docs;
- plugin SDK docs;
- acceptance evidence.

## R2 Migration safety

Every schema change must have:

- forward migration;
- rollback/recovery strategy;
- test fixture;
- compatibility check;
- backup consideration.

## R3 Recovery

Verify:

- interrupted jobs;
- stale leases;
- partial workflows;
- cancelled tasks;
- process restart;
- database recovery;
- plugin quarantine;
- failed AI requests;
- failed media jobs;
- failed indexing.

## R4 Observability

Verify:

- bounded logs;
- useful error classification;
- operator diagnostics;
- no secret leakage;
- job visibility;
- plugin visibility;
- Telegram traffic visibility;
- search/index visibility.

## R5 Systemd

Verify:

- startup;
- restart;
- shutdown;
- health;
- dependency ordering;
- failure recovery.

## R6 Performance

Measure:

- startup;
- command latency;
- search latency;
- index cost;
- SQLite growth;
- media workspace growth;
- job concurrency;
- Telegram request pressure;
- AI request pressure.

No optimization without measurements.

---

# 19. Final release acceptance

The final release is not complete until:

## Architecture

- modular monolith preserved;
- no duplicate job/event/storage authority;
- ApplicationContext remains the service composition root.

## Telegram

- transport governed;
- state cache rebuildable;
- events durable;
- archive resumable;
- destructive actions authorized and bounded.

## Product

- command contract complete;
- help/discovery complete;
- unified search complete;
- entity inspector complete;
- interactive UX mature;
- plugin UX complete;
- operator control plane complete.

## Intelligence

- IOC normalization;
- IntelGraph;
- correlation;
- provenance;
- evidence;
- timeline;
- cases;
- contradiction handling;
- no unsupported identity claims.

## AI

- provider-independent;
- bounded;
- advisory;
- context-aware;
- integrated with search/media/evidence/cases;
- no silent mutation.

## Media

- practical workflows;
- intelligence evidence;
- hashes;
- OCR/STT;
- search;
- case integration.

## Safety

- public/authorized scope;
- no anti-ban;
- no evasion;
- no credential harvesting;
- no secret persistence;
- no unauthorized active scanning.

## Operations

- health;
- doctor;
- status;
- jobs;
- plugins;
- storage;
- AI;
- isolation;
- recovery;
- update/restart;
- systemd validation.

## Testing

- focused gate tests;
- integration tests;
- full regression;
- compileall;
- production acceptance;
- owner-host/live smoke tests.

---

# 20. Execution protocol for every future gate

For each gate, follow exactly:

```
1. READ
   ↓
2. AUDIT CURRENT CODE
   ↓
3. INVENTORY EXISTING CAPABILITIES
   ↓
4. IDENTIFY PREREQUISITES
   ↓
5. VERIFY PREREQUISITES
   ↓
6. DEFINE GAP
   ↓
7. IMPLEMENT MINIMUM PLATFORM CONTRACT
   ↓
8. IMPLEMENT PRODUCT SURFACE
   ↓
9. ADD FOCUSED TESTS
   ↓
10. ADD FAILURE / RECOVERY TESTS
   ↓
11. RUN FULL REGRESSION
   ↓
12. RUN OWNER-HOST / LIVE VALIDATION
   ↓
13. UPDATE DOCUMENTATION
   ↓
14. RECORD ACCEPTANCE EVIDENCE
   ↓
15. ONLY THEN CLOSE THE GATE
```

Research can run in parallel with implementation **only when it does not become a hidden prerequisite**. If implementation depends on the research outcome, the research gate blocks implementation.

---

# 21. Immediate execution queue

Do not start a new numbered “Phase 11.”

Start here:

### NEXT — Gate A

**Command Contract + Discoverability**

Exact first actions:

1. inspect `core/registry.py` and all command registration paths;
2. inspect command models/metadata;
3. inventory all current commands and aliases;
4. inspect `.help` and command search;
5. inspect permission and operation-class handling;
6. compare implementation to `CMD-1..5` and `UX-CMD-1`;
7. produce a concrete gap list;
8. implement the missing contract fields and discovery layer;
9. migrate representative existing commands;
10. add focused acceptance tests;
11. run full regression;
12. update roadmap evidence;
13. close Gate A only when the full evidence contract passes.

### Then

```
Gate B — Unified Search
Gate C — Entity Inspector
Gate D — Correlation UX
Gate E — Interactive UX
Gate F — Plugin UX
Gate G — AI UX
Gate H — Control Plane
Product Maturity Gate
Dataset/HF research gates
Remaining adapters/media
Release hardening
Final acceptance
```

---

# 22. Relationship to existing roadmap files

This execution roadmap intentionally preserves the existing repository roadmap hierarchy.

### `ROADMAP.md`

Remains the complete historical and capability roadmap, including:

- Programs A–T;
- Telegram core/state/events;
- archive;
- UX/product;
- AI;
- automation;
- IntelGraph;
- IOC;
- Telegram intelligence;
- identity intelligence;
- domain/infrastructure intelligence;
- link intelligence;
- media intelligence;
- timeline/cases;
- security intelligence;
- Git/public-code intelligence;
- plugin ecosystem;
- competitive catch-up;
- release/operations;
- dataset lineage and Hugging Face prerequisites;
- competitive product maturity;
- roadmap completion rules.

### `ROADMAP_COMPETITIVE_ADDENDUM.md`

Remains the source for:

- COMP-1;
- CMD-1..5;
- UX-CMD-1;
- SEARCH-1..4;
- INSPECT-1..4;
- CORR-1..5;
- SDK-1..5;
- CTRL-1..4;
- competitive target clarification;
- cross-cutting completion rule.

### This file

Is the **execution reconciliation layer**:

- what is already accepted;
- what is partial;
- what is missing;
- prerequisites;
- implementation order;
- acceptance requirements;
- next concrete gate.

No existing roadmap item is removed by this document.

---

# 23. Governing principle

AstraUserbot should not become a collection of isolated features.

The final product spine is:

```
Telegram
   ↓
Events / State
   ↓
Archive / Media
   ↓
Search
   ↓
Commands / Discovery
   ↓
Entity Inspector
   ↓
IOC / IntelGraph
   ↓
Correlation
   ↓
Evidence
   ↓
Timeline / Cases
   ↓
AI explanation / synthesis
   ↓
Automation
   ↓
Operator Control Plane
   ↓
Recovery / Observability
```

And the engineering rule remains:

> **Discover → normalize → verify lineage → select authoritative sources → implement → correlate → prove → release.**

The product target is not maximum command count.

The target is a **mature, discoverable, evidence-aware, durable, recoverable, zero-cost Telegram automation and local-intelligence platform** that preserves the production-grade engineering foundation already achieved.
