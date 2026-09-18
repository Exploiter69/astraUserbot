# AstraUserbot Roadmap

**Roadmap status:** Active planning baseline  
**Current release:** `1.0.0`  
**Target direction:** AstraUserbot 2.x  
**Primary constraint:** ₹0 / $0  
**Architecture constraint:** preserve the existing single-process Python/asyncio modular-monolith design

> **Power belongs at the plugin edge. Reliability belongs in the platform core.**

This document is the implementation roadmap for the next major AstraUserbot program. It is intentionally feature-rich, but it is not a promise to implement everything in one release. Work proceeds gate-by-gate, with each gate leaving the repository runnable, tested and recoverable.

---

## 1. Product destination

AstraUserbot 2.x will evolve from a hardened userbot platform into four tightly integrated capabilities:

1. **Telegram Platform** — high-throughput, rate-aware, observable Telegram operations;
2. **Userbot Product** — a broad, polished, discoverable command and automation surface;
3. **Local Intelligence Workstation** — public-source intelligence, IOC/entity correlation, timelines and cases;
4. **Durable Automation Engine** — persistent rules and workflows backed by the existing JobEngine.

The differentiator is not simply command count. Astra should combine mature-userbot breadth with stronger durability, isolation, observability, recovery and evidence discipline.

### End-state principle

Every new feature should answer at least one of these questions:

- Does it extract more value from an existing Telegram interaction?
- Does it make Telegram operations safer, faster or more observable?
- Does it reduce repetitive owner work?
- Does it turn messages/media/public information into searchable local knowledge?
- Does it provide durable, recoverable automation?
- Does it improve the user experience without weakening the platform contracts?

Avoid feature inflation that produces many shallow duplicate commands.

---

## 2. Non-negotiable constraints

### 2.1 Architecture

Keep:

- Python + asyncio;
- Telethon as Telegram transport;
- SQLite/WAL as the default durable store;
- existing ApplicationContext/shared services;
- existing TaskSupervisor for ephemeral work;
- existing JobEngine for restart-sensitive work;
- existing Media, Search, AI, Isolation and Storage services;
- real Bubblewrap isolation where classification requires it;
- plugin-first feature delivery.

Do **not** turn Astra into a distributed system merely to add features.

### 2.2 Cost

The project remains ₹0/$0:

- no paid API requirement;
- no paid hosting requirement;
- no mandatory SaaS dependency;
- no mandatory hosted database;
- no mandatory local LLM;
- local/free providers may be adapters, never architectural authorities.

### 2.3 Safety

Astra may process public or legitimately observable information and authorized assets. Intelligence features must not become credential theft, private-data acquisition, unauthorized surveillance, intrusive scanning, restriction circumvention or anti-ban tooling.

Explicitly forbidden as roadmap goals:

- account rotation to evade Telegram restrictions;
- fake clients/fingerprint spoofing;
- FloodWait bypass mechanisms;
- PeerFlood bypass mechanisms;
- credential harvesting;
- storing recovered passwords, tokens or secrets;
- unauthorized active network scanning;
- claiming identity from weak username correlations as fact.

### 2.4 Authority

AI remains advisory. A model may propose, classify, summarize or plan; it does not become an authorization layer, mutation authority or source of truth.

---

# 3. Program map

The roadmap is divided into implementation programs rather than arbitrary feature dumps.

| Program | Area | Primary outcome |
|---|---|---|
| A | Telegram Core 2.0 | rate-aware, prioritized, observable Telegram transport |
| B | Telegram State Engine | entity/dialog/capability cache and incremental synchronization |
| C | Telegram Event Engine | durable events, projections and replay |
| D | Archive Engine | bounded searchable Telegram archival |
| E | Telegram UX + Product | mature userbot feature breadth and polished UX |
| F | AI Product 2.0 | unified, safe, context-aware AI surface |
| G | Automation Engine | durable rules and multi-step Telegram workflows |
| H | IntelGraph | local entity/relationship intelligence graph |
| I | IOC Engine | deterministic indicator extraction, normalization and enrichment |
| J | Telegram Intelligence | TGINTEL and observable relationship analysis |
| K | Identity/Username Intelligence | public-source pivots with evidence/confidence |
| L | Domain/Infrastructure Intelligence | DNS/RDAP/TLS/CT/web/infrastructure graph |
| M | Link Intelligence | URL, redirect and domain correlation |
| N | Media Intelligence | hashes, OCR, speech, frames and evidence fusion |
| O | Timeline + Cases | investigation timelines and durable case records |
| P | Security Intelligence | phishing/IOC/link/homoglyph defensive analysis |
| Q | Git/Public-Code Intelligence | public repository intelligence |
| R | Plugin Ecosystem | mature third-party plugin contract and registry |
| S | Competitor Catch-up | systematic useful feature parity |
| T | Release/Operations | acceptance gates, migrations, observability and recovery |

---

# 4. Gate discipline

No roadmap program is considered complete because code exists. A gate completes only when the implementation has:

1. architecture/design recorded;
2. migrations, if required, defined and tested;
3. unit/integration/contract tests;
4. resource bounds;
5. cancellation behavior;
6. failure classification;
7. authorization boundaries;
8. diagnostics/metrics where operationally relevant;
9. documentation;
10. production acceptance evidence;
11. no regression in the existing production acceptance gate.

### Gate naming

Use stable names such as:

- `TG-1`, `TG-2` … for Telegram Core;
- `STATE-1` … for state engine;
- `EVENT-1` … for event engine;
- `UX-1` … for product UX;
- `AI-1` … for AI;
- `AUTO-1` … for automation;
- `INTEL-1` … for intelligence foundation;
- etc.

Each gate should normally be implemented as one coherent change set rather than a collection of unrelated micro-edits.

---

# 5. Program A — Telegram Core 2.0

## A1. TelegramTrafficController

Create a transport-level controller beneath `TelegramFacade` rather than duplicating rate logic in plugins.

Responsibilities:

- global Telegram concurrency limit;
- per-method budgets;
- per-peer budgets;
- operation classification;
- priority scheduling;
- adaptive cooldown;
- FloodWait learning;
- SlowMode handling;
- retry classification;
- durable telemetry;
- cancellation-safe waits.

### Operation classes

- `READ`
- `WRITE`
- `DESTRUCTIVE`
- `MEDIA`
- `DISCOVERY`
- `BULK`
- `INTERACTIVE`
- `RECOVERY`

### Priority classes

- `P0` owner command;
- `P1` interactive Telegram action;
- `P2` normal plugin operation;
- `P3` background synchronization;
- `P4` indexing/archive;
- `P5` maintenance.

The scheduler must prevent low-priority indexing from starving owner commands.

## A2. Adaptive Telegram governor

Model pressure separately at:

- account-wide level;
- method level;
- peer level.

Use feedback from actual Telegram responses instead of fixed fake delays.

Circuit states:

`NORMAL → PRESSURE → THROTTLED → COOLDOWN → PROBE → NORMAL`

Transitions must be deterministic and observable.

## A3. Telegram flight recorder

Add a durable `telegram_operations` record containing, as appropriate:

- operation ID;
- timestamp;
- method;
- peer ID;
- operation class;
- request hash;
- result classification;
- latency;
- FloodWait seconds;
- SlowMode seconds;
- PeerFlood indicator;
- forbidden/error class;
- retry count;
- payload size;
- job ID;
- plugin/source.

Sensitive request contents must not be persisted.

## A4. Operator commands

Add:

- `.tghealth`
- `.tgtraffic`
- `.tgfloods`
- `.tgpeer`
- `.tgmethod`
- `.tgdiag`

Add a compact pressure HUD to operator diagnostics without turning normal messages into telemetry spam.

### Acceptance

TG-1 through TG-5 must prove that Telegram calls are centrally governed, priorities work, FloodWait behavior is learned, telemetry is bounded, and existing plugins continue to work.

---

# 6. Program B — Telegram State Engine

## B1. Entity intelligence/cache

Maintain locally derived entity information such as:

- entity ID;
- access hash when legitimately available;
- username;
- title/name;
- entity type;
- last seen;
- relevant permissions/capabilities;
- photo metadata where appropriate.

Never treat stale cache data as current authority when Telegram must be queried for a mutation.

## B2. Dialog cache

Persist a bounded local representation of known dialogs to reduce repeated discovery work.

Track:

- peer;
- dialog type;
- title/username snapshot;
- last observed message ID;
- last synchronization time;
- sync state.

## B3. Capability cache

Expose `.tgcap <peer>` with capabilities such as:

- can read;
- can send;
- can edit;
- can delete;
- can pin;
- can react;
- slow mode;
- relevant restrictions.

Capabilities are observations with timestamps, not permanent truth.

## B4. Incremental synchronization

Persist synchronization cursors:
- chat ID;
- last message ID;
- last synced timestamp;
- sync state;
- gap detected flag.

Support resumable bounded synchronization rather than repeatedly scanning complete histories.

### Acceptance

`STATE-*` gates prove cache rebuildability, stale-state handling, bounded storage, gap detection and compatibility with the existing entity resolution layer.

---

# 7. Program C — Telegram Event Engine

## C1. Event collector

Normalize relevant Telegram updates into local durable events.

Initial event families:

- `MESSAGE_NEW`
- `MESSAGE_EDIT`
- `MESSAGE_DELETE`
- `REACTION_CHANGED`
- `CHAT_MEMBER_CHANGED`
- `CALL_STATE_CHANGED`
- future supported event types as the transport evolves.

## C2. Durable event journal

Store normalized event envelopes with:

- event ID;
- event type;
- observed timestamp;
- source peer;
- source message/entity IDs;
- normalized payload;
- schema version;
- processing state.

Do not copy unlimited raw Telegram payloads into SQLite.

## C3. Projections

Build rebuildable projections for:

- latest message state;
- entity observations;
- IOC observations;
- timeline entries;
- archive metadata.

## C4. Replay engine

Allow selected projections to be rebuilt from durable event history.

Replay must be bounded, observable and safe to interrupt.

---

# 8. Program D — Telegram Archive Engine

Provide bounded commands such as:

- `/archive chat`
- `/archive channel`
- `/archive since`
- `/archive media`
- `/archive search`

Pipeline:

`Telegram → bounded fetch workers → SQLite metadata → FTS5 → media workspace`

Requirements:

- resumable jobs;
- deduplication;
- content-addressed media;
- explicit scope limits;
- progress reporting;
- cancellation;
- no unbounded memory accumulation.

### Takeout sessions

Use Telegram takeout sessions for suitable bulk export/history operations where they provide a legitimate and safer bulk path. Takeout is an optimization, not a mandatory dependency.

---

# 9. Program E — Telegram UX + Product Expansion

This program closes the biggest post-hardening weakness: user-facing breadth and polish.

## E1. Productivity

Build/upgrade:

- AFK;
- notes;
- reminders;
- filters;
- saved-message helpers;
- bookmarks;
- templates;
- reusable snippets;
- message utilities;
- owner-oriented task controls.

## E2. Group management

Build/upgrade where supported by Telegram permissions:

- purge;
- mass delete;
- ban/unban;
- mute/unmute;
- warn;
- kick;
- pin/unpin;
- lockdown;
- welcome/goodbye;
- anti-spam;
- moderation reports;
- moderation audit history.

Destructive operations require explicit authorization, bounded targets and confirmation where appropriate.

## E3. Telegram utilities

Expand useful utilities rather than meme-command volume:

- message inspection;
- entity inspection;
- chat diagnostics;
- formatting helpers;
- IDs/links;
- reply/reference utilities;
- bulk-but-bounded message operations.

## E4. Media utilities

Expand practical media workflows:

- conversion;
- extraction;
- compression under limits;
- metadata inspection;
- screenshots/frame extraction;
- safe archive/export helpers.

## E5. Web/network utilities

Build practical public-web tools around the existing HTTP/network services, including safe DNS/header/IP/HTTP inspection.

---

# 10. Program E continued — Telegram UX 2.0

Create a consistent interaction layer:

- inline buttons;
- callback actions;
- pagination;
- menus;
- confirmation prompts;
- reply-based workflows;
- progress updates;
- durable job controls;
- cancel/retry/status actions;
- concise structured errors;
- better command discovery/help.

The UX layer must remain compatible with ordinary text commands. Interactive UI is an enhancement, not a replacement for deterministic command contracts.

---

# 11. Program F — AI Product 2.0

Do not resurrect the four quarantined legacy AI plugins. Build the new AI surface on the existing provider-independent AI service.

## F1. Unified commands

Target product surface:

- `.ai`
- `.ask`
- `.explain`
- `.summarize`
- `.rewrite`
- `.translate`
- `.extract`
- `.code`

Exact command ownership and semantics will be defined during implementation to avoid collisions with existing plugins.

## F2. Context-aware Telegram AI

AI may receive explicitly selected context such as:

- replied message;
- bounded message window;
- selected chat history;
- local archive results;
- OCR text;
- transcription;
- intelligence observations.

Context must be bounded and privacy-conscious.

## F3. AI jobs

Long AI operations run through JobEngine when restart/retry semantics matter.

The AI layer must enforce:

- provider timeout;
- request bounds;
- response bounds;
- cancellation;
- budget/rate controls;
- malformed-output rejection;
- no tool/function mutation authority;
- provider fallback only where explicitly allowed.

## F4. Zero-cost provider strategy

Support local/free providers already compatible with Astra. No provider may become a mandatory architectural dependency.

---

# 12. Program G — Automation Engine

Transform useful repeated Telegram actions into durable rules.

## G1. Rule model

Represent rules using:

`WHEN / WHERE / MATCH / ACTION`

Persist rules in SQLite with versioned schemas.

## G2. Trigger types

Examples:

- message received;
- message edited;
- media observed;
- scheduled time;
- job completion;
- intelligence observation;
- explicit owner command.

## G3. Actions

Actions are explicit, authorized and bounded:

- reply;
- forward where authorized;
- tag/index;
- archive;
- notify owner;
- invoke safe plugin action;
- start a durable job.

## G4. Transactional workflows

Multi-step workflows emit durable states such as:

- `ACTION_STARTED`
- `STEP_COMPLETED`
- `STEP_FAILED`
- `RECOVERY_REQUIRED`

Integrate with JobEngine recovery and fencing rather than inventing a second job system.

---

# 13. Program H — IntelGraph

IntelGraph is the foundation of the intelligence side of Astra.

## H1. Core data model

Initial concepts:

- `entities`
- `relationships`
- `observations`
- `sources`
- `confidence`
- timestamps

Example relationship types:
- `OWNS`
- `USES`
- `RESOLVES_TO`
- `MENTIONS`
- `LINKS_TO`
- `POSTED`
- `SEEN_WITH`
- `SHARES_HASH`
- `SHARES_USERNAME`
- `SHARES_DOMAIN`

Every relationship should be traceable to observations/sources and time.

## H2. Graph queries

Target command:

`.intel graph <target>`

Graph output should be bounded and readable in Telegram, with deeper output available through paginated views or exported reports.

## H3. Correlation

Correlation must distinguish:

- observed fact;
- derived relationship;
- weak signal;
- strong corroborated signal;
- contradiction;
- unknown.

Never convert correlation into an unsupported identity claim.

---

# 14. Program I — IOC Engine

## I1. Extraction

Extract indicators from messages/media/documents where useful:

- IPv4/IPv6;
- domains;
- URLs;
- emails;
- Telegram usernames;
- hashes;
- CVE identifiers;
- package names;
- filenames;
- ASNs;
- ports;
- coordinates;
- timestamps;
- other clearly defined indicator classes.

## I2. Normalization

Canonicalize indicators before storage and correlation.

Examples:

- URL normalization;
- domain case normalization;
- hash algorithm identification;
- username normalization;
- IP canonicalization;
- IDN/punycode representation.

## I3. IOC interface

Target:

`.ioc <indicator>`

Return:

- type;
- observations;
- related DNS/ASN/org data where available;
- related URLs;
- Telegram references;
- local observations;
- first/last seen;
- confidence;
- evidence reasons.

## I4. IOC watch

Target:

- `.ioc watch <indicator>`
- `.ioc diff <indicator>`

Watch jobs detect new local/public observations without aggressive polling.

---

# 15. Program J — Telegram Intelligence (TGINTEL)

## J1. Observable Telegram intelligence

Target:

`.tgintel @public_username`

Possible fields, only when legitimately observable:

- account/entity ID;
- username;
- display name;
- bio;
- public links;
- public groups/channels;
- observable activity;
- forwards;
- mentions;
- referenced domains;
- media observations;
- timestamps.

## J2. Relationship graph

Target:

`.tggraph @alice`

Graph entities may include:

- users;
- channels;
- groups;
- domains;
- URLs;
- messages;
- media;
- forwards;
- mentions.

Scope and privacy rules must prevent accidental broad collection.

## J3. Selected-chat intelligence feed

Target:

`.intel on`

Enable collection for explicitly selected chats. Ingestion should be bounded, observable and disable-able.

---

# 16. Program K — Username / Entity Intelligence

## K1. Username pivots

Target:

`.intel username <handle>`

Public sources may include supported public profiles and public indexed pages such as GitHub, GitLab, Reddit, Mastodon, X/public profiles and public websites.

Each source result must be classified:

- `FOUND`
- `NOT_FOUND`
- `UNKNOWN`
- `BLOCKED`
- `AMBIGUOUS`

## K2. Deterministic mutations

Generate bounded variants such as:

- underscore variants;
- dot/hyphen variants;
- name + digits;
- deterministic separator changes.

Do not generate unlimited candidate floods.

## K3. Evidence model

Possible signals:

- same username: weak;
- same public URL: stronger;
- same domain: contextual;
- same avatar hash: supporting;
- explicit cross-link: strong;
- same public email: strong;
- contradiction: negative evidence.

Weights are configuration, not universal truth. Reports must explain why a relationship was scored.

---

# 17. Program L — Domain / Infrastructure Intelligence

Build on the existing network OSINT package and central HTTP service.

## L1. Domain intelligence

Support bounded public checks for:

- DNS;
- WHOIS/RDAP where publicly available;
- ASN;
- TLS certificates;
- Certificate Transparency;
- subdomains from public sources;
- HTTP metadata;
- redirects;
- technologies;
- favicon hash;
- robots.txt;
- security.txt;
- MX/SPF/DKIM/DMARC observations.

## L2. Certificate Transparency

Target:

`.cert example.com`

Track:

- certificate identity;
- SANs;
- wildcard coverage;
- issuer;
- validity;
- first/last seen;
- related domains.

## L3. Infrastructure graph

Example flow:

`domain → CT → DNS → IP → ASN → related domains → HTTP metadata`

Active checks must remain separately classified and restricted to authorized assets.

## L4. Web technology fingerprinting

Capture bounded observations for:

- server;
- framework;
- CMS;
- JS/CDN signals;
- reverse proxy;
- TLS;
- security headers;
- cookies;
- robots/well-known resources.

---

# 18. Program M — Link Intelligence

Build a normalized link graph:

`URL → domain → IP → certificate → redirects → Telegram messages → media`

Features:

- URL normalization;
- redirect-chain analysis;
- domain correlation;
- public reputation adapters where legitimately/free available;
- suspicious-link scoring;
- local observation history;
- IOC extraction from URLs/pages.

Never automatically visit arbitrary links without bounded HTTP/resource policy.

---

# 19. Program N — Media Intelligence 2.0

The media pipeline becomes an evidence-producing intelligence pipeline.

## N1. Content addressing

Use SHA-256 content hashes for deterministic deduplication.

Pipeline:

`download → hash → dedup → classify → process → upload/archive/discard`

## N2. Perceptual clustering

Where safe and useful, support:

- pHash;
- dHash;
- aHash;
- video frame fingerprints.
Exact SHA-256 remains the authoritative byte identity; perceptual hashes are similarity signals.

## N3. Screenshot intelligence

Extract where available:

- OCR text;
- URLs;
- handles;
- dates/timestamps;
- application/UI fingerprints;
- visible indicators;
- media hashes.

## N4. Audio/video intelligence

Fuse:

- audio extraction;
- speech-to-text where available;
- frame sampling;
- OCR;
- entity extraction;
- IOC extraction.

All processing remains bounded by existing Media/Isolation contracts.

---

# 20. Program O — Timeline + Case System

## O1. Timeline engine

Target:

`.timeline <target>`

Timeline entries include:

- first seen;
- last seen;
- source;
- timestamp;
- event type;
- confidence;
- supporting observation.

## O2. Case system

Commands:

- `.case new`
- `.case add`
- `.case graph`
- `.case timeline`
- `.case report`

Tables/entities:

- `cases`
- `case_entities`
- `case_observations`
- `case_notes`
- `case_sources`
- `case_events`

Cases are durable local records, not a remote SaaS workflow.

## O3. Reports

Reports should separate:

1. verified observations;
2. derived correlations;
3. confidence;
4. contradictions;
5. unknowns;
6. source/time evidence.

---

# 21. Program P — Security Intelligence

Defensive security features include:

- suspicious-link detector;
- phishing-domain detector;
- IOC extraction;
- URL reputation adapters;
- attachment/hash reputation where legally/publicly available;
- homoglyph detector;
- punycode detector;
- mixed-script detection;
- redirect-chain analyzer;
- message risk scoring.

## Homoglyph / IDN analysis

Show:

- ASCII representation;
- punycode;
- Unicode script composition;
- mixed-script warnings;
- visual-similarity indicators.

Do not present visual similarity as proof of maliciousness.

---

# 22. Program Q — Git / Public-Code Intelligence

Target:

`.gitintel owner/repo`

Collect only public repository information:

- metadata;
- contributors;
- branches;
- releases;
- issues;
- commits;
- technologies;
- dependencies;
- public domains;
- public emails where intentionally published;
- security references.

Do not harvest secrets or credentials from public code. If exposed credentials are encountered, reports should avoid storing the secret value and should classify the finding defensively.

---

# 23. Program R — Plugin Ecosystem

Turn Astra's plugin system into a mature ecosystem without weakening the core.

## R1. Plugin SDK

Improve:

- manifests;
- versioning;
- dependencies;
- permissions;
- lifecycle hooks;
- command declarations;
- compatibility declarations;
- migrations;
- health metadata;
- safe failure/quarantine behavior.

## R2. Plugin registry

A future registry can use GitHub/public repository metadata and remain optional. No mandatory hosted registry service.

## R3. Safety metadata

Every plugin should declare relevant capabilities, for example:

- Telegram read;
- Telegram write;
- destructive Telegram action;
- filesystem;
- network;
- subprocess;
- media;
- AI;
- intelligence collection.

## R4. Ecosystem compatibility

Prefer stable shared services over plugins directly creating infrastructure clients.

---

# 24. Program S — Competitor Feature Catch-up

Use mature projects such as CipherElite, CatUserbot, Hikka, Userge, Paperplane, UniBorg, Kaguya and Project Akasha as feature references, not architectural authorities.

Systematically audit useful gaps in:

- command breadth;
- moderation;
- productivity;
- Telegram utilities;
- inline UX;
- media tools;
- PM protection;
- search/inspection;
- plugin discovery;
- plugin ecosystem;
- AI interaction.

Do not copy low-value command volume merely to match a headline count.

### Competitive target

Astra should eventually:

- match or exceed mature-userbot feature breadth;
- approach Hikka/CipherElite-level interaction UX;
- provide a safer AI product surface;
- approach CatUserbot/Hikka/Userge ecosystem breadth;
- retain substantially stronger durability/recovery/isolation discipline.

Exact parity is measured by an auditable feature matrix, not marketing claims.

---

# 25. Program T — Release and Operations

Every major program gets operational treatment.

## T1. Metrics

Extend existing metrics for:

- Telegram pressure;
- queue depth;
- job latency;
- archive throughput;
- intelligence ingestion;
- cache freshness;
- provider usage;
- media processing;
- failure/recovery rates.

## T2. Diagnostics

Operator diagnostics should answer:

- what is running;
- what is queued;
- what is blocked;
- what failed;
- what is retrying;
- what is stale;
- what is waiting on Telegram;
- what needs owner action.

## T3. Acceptance

The existing production acceptance gate remains the baseline regression gate. New gates are additive.

## T4. Recovery

All new durable systems need:

- migration path;
- backup/restore compatibility;
- corruption/failure behavior;
- resumability;
- cleanup/retention policy;
- rollback strategy.

---

# 26. Recommended implementation order

The roadmap is intentionally broad, but implementation order matters.

## Phase 1 — Telegram Core

1. `TG-1` TelegramTrafficController
2. `TG-2` adaptive FloodWait governor
3. `TG-3` operation telemetry/flight recorder
4. `TG-4` priority queues
5. `TG-5` entity/dialog cache
6. `TG-6` Telegram capability discovery

**Exit:** all Telegram operations have a safe central control path.

## Phase 2 — Telegram State + Events

7. `STATE-1` incremental synchronization model
8. `STATE-2` gap detection/recovery
9. `EVENT-1` event collector
10. `EVENT-2` durable event journal
11. `EVENT-3` projections
12. `EVENT-4` replay

**Exit:** Telegram-derived state is durable, rebuildable and incrementally maintained.

## Phase 3 — Archive + UX Foundation

13. `ARCH-1` archive job model
14. `ARCH-2` bounded history/media archive
15. `UX-1` interaction primitives
16. `UX-2` pagination/progress/cancel
17. `UX-3` help/discovery/error UX

**Exit:** Astra has a durable archive and polished interaction substrate.

## Phase 4 — Product Feature Expansion

18. productivity feature family
19. moderation feature family20. Telegram utility family
21. media utility family
22. web/network utility family
23. command-by-command collision/permission audit

**Exit:** Astra closes the largest mature-userbot product gaps.

## Phase 5 — AI Product 2.0

24. `AI-1` unified AI command surface
25. `AI-2` bounded Telegram context
26. `AI-3` media/OCR/STT integration
27. `AI-4` durable AI jobs
28. `AI-5` AI diagnostics/limits

**Exit:** AI is a coherent product, not a collection of legacy wrappers.

## Phase 6 — Automation

29. `AUTO-1` rule schema
30. `AUTO-2` trigger engine
31. `AUTO-3` action authorization
32. `AUTO-4` durable workflow execution
33. `AUTO-5` recovery/retry integration

**Exit:** repeated user workflows can run durably without turning AI into authority.

## Phase 7 — Intelligence Foundation

34. `INTEL-1` IntelGraph schema
35. `INTEL-2` observation/source/confidence model
36. `INTEL-3` IOC extraction
37. `INTEL-4` normalization/deduplication
38. `INTEL-5` timeline primitives

**Exit:** Astra has a trustworthy local intelligence substrate.

## Phase 8 — Intelligence Sources

39. `TGINTEL-1` Telegram intelligence collector
40. `USER-1` username pivot engine
41. `DOMAIN-1` domain intelligence
42. `DOMAIN-2` Certificate Transparency
43. `LINK-1` redirect/link graph
44. `GIT-1` public-code intelligence

**Exit:** multiple public-source domains feed the same graph and evidence model.

## Phase 9 — Media + Investigation

45. `MEDIAINTEL-1` content-addressed media observations
46. `MEDIAINTEL-2` perceptual clustering
47. `MEDIAINTEL-3` screenshot intelligence
48. `MEDIAINTEL-4` audio/video intelligence fusion
49. `CASE-1` case schema
50. `CASE-2` case graph/timeline
51. `CASE-3` report generation

**Exit:** messages and media can become durable, traceable investigation evidence.

## Phase 10 — Security + Ecosystem

52. `SEC-1` suspicious-link/risk engine
53. `SEC-2` homoglyph/IDN analysis
54. `SEC-3` defensive reputation adapters
55. `SDK-1` plugin capability metadata
56. `SDK-2` registry/compatibility tooling
57. `COMP-1` competitor feature matrix
58. `COMP-2` final feature catch-up passes

**Exit:** Astra has broad product capability plus a sustainable extension model.

---

# 27. Feature completion definition

A feature is **not done** when its command works once.

A feature is done when:

- command ownership is deterministic;
- permissions are explicit;
- inputs are bounded;
- resource consumption is bounded;
- Telegram traffic is governed;
- durable work uses JobEngine when necessary;
- destructive effects are authorized;
- errors are classified;
- cancellation is safe;
- retries are intentional;
- outputs are verified where practical;
- sensitive data is excluded from ordinary logs;
- tests cover normal and failure paths;
- operator diagnostics exist when needed;
- documentation exists;
- production acceptance remains green.

---

# 28. Data and retention principles

New data must have an explicit owner.

### Durable source of truth

SQLite remains authoritative for durable application state.

### Derived data

Caches, search indexes, projections and graph indexes must be rebuildable whenever practical.

### Retention

Every high-volume table must define:

- retention duration/count;
- compaction strategy;
- indexing strategy;
- cleanup behavior;
- maximum growth expectations.

### Evidence

Intelligence observations should retain enough provenance to answer:

- where did this come from?
- when was it observed?
- what exact signal produced it?
- how confident is the relationship?
- what contradicts it?

---

# 29. Observability principles

Astra should increasingly expose three levels of state:

### User level

Simple output: success, result, progress, failure and next action.

### Operator level

`.health`, `.status`, `.ops`, `.tghealth`, `.tgtraffic`, `.jobs`, `.diagnostics` and future intelligence diagnostics.

### Evidence level

Durable records containing IDs, timestamps, classifications and provenance without leaking secrets or unbounded raw payloads.

---

# 30. Performance principles

The goal is not maximum request rate. The goal is maximum useful work per Telegram interaction and per unit of local compute.

Prefer:

- batching where Telegram semantics allow it;
- caching;
- incremental synchronization;
- deduplication;
- priority scheduling;
- local search;
- content addressing;
- replayable projections;
- bounded concurrency.

Avoid:

- blind polling;
- repeated full-history scans;
- duplicate media processing;
- unnecessary model calls;
- unbounded background workers.

> **Don't ask Telegram more often. Extract more value from every Telegram interaction.**

---

# 31. Security and privacy principles

Intelligence collection must be intentionally scoped.

- Public/legitimately observable information only.
- Explicit chat selection for persistent Telegram intelligence feeds.
- No credential storage.
- No secret values in reports/logs.
- No unauthorized active scanning.
- No restriction circumvention.
- No identity certainty from weak correlations.
- Every high-confidence relationship needs explainable evidence.
- Destructive Telegram operations remain authorization-gated.
- External HTTP requests remain resource-bounded and observable.

---

# 32. What we are deliberately not building

This roadmap does **not** authorize:

- migration from Telethon to another Telegram library;
- migration from SQLite to PostgreSQL as a prerequisite;
- Redis/Kafka/RabbitMQ/Celery/Kubernetes;
- microservices for their own sake;
- mandatory LiteLLM/LangChain/LlamaIndex;
- mandatory hosted infrastructure;
- paid APIs;
- anti-ban systems;
- FloodWait/PeerFlood bypasses;
- credential harvesting;
- private-account intrusion;
- unlimited scraping;
- AI-controlled destructive actions;
- a second competing workflow engine;
- a second competing storage authority.

---

# 33. Definition of the Astra 2.x end state

When the roadmap has matured, Astra should look like this:

```text
                         TELEGRAM
                            │
                    ┌───────▼────────┐
                    │ Traffic / Auth │
                    │ / Entity State │
                    └───────┬────────┘
                            │
                 ┌──────────▼──────────┐
                 │ Event + Application │
                 │      Boundary       │
                 └───────┬─────┬───────┘
                         │     │
             ┌───────────┘     └────────────┐
             ▼                              ▼
       PRODUCT / UX                    EVENT JOURNAL
             │                              │
       ┌─────┼─────┐                        ▼
       ▼     ▼     ▼                    PROJECTIONS
     Media  AI  Automation                  │
                                             ▼
                                    INTEL / SEARCH / ARCHIVE
                                             │
                          ┌──────────────────┼─────────────────┐
                          ▼                  ▼                 ▼
                      IntelGraph         Timeline           Cases
                          │                  │                 │
                          └──────────────────┼─────────────────┘
                                             ▼
                                           Reports
```

The platform underneath remains the same disciplined core: SQLite/WAL, durable jobs, bounded resources, real isolation, explicit permissions, deterministic plugins, evidence-first diagnostics and zero-cost operation.

---

# 34. First implementation gate

The next implementation target is **TG-1: TelegramTrafficController**.

Before writing the controller, the implementation pass must inspect the current Telegram facade/service, all Telegram call paths, JobEngine interaction, plugin service access and existing rate/error handling. The goal is to centralize control without breaking current plugins.

TG-1 should end with:

- controller abstraction;
- operation classification;
- bounded global concurrency;
- plugin/service integration;
- tests for admission, cancellation and priority behavior;
- no bypass path for ordinary Telegram operations;
- production acceptance regression green;
- documentation updated.

After TG-1 passes, proceed to TG-2 rather than implementing later roadmap programs prematurely.

---

# 35. Working rule for this roadmap

This file is the long-term feature map. Individual implementation gates should record their detailed design, test evidence and migration decisions in the appropriate architecture/operation documents rather than turning this roadmap into a changelog.

Update this roadmap when scope changes materially. Do not rewrite completed history to make progress look cleaner.

**Roadmap objective:** make AstraUserbot one coherent, feature-rich, zero-cost Telegram automation and local intelligence platform without sacrificing the production-grade engineering foundation already achieved in v1.0.0.

---

# 36. Master dependency model — prerequisites are first-class

The roadmap above remains intact. From this point forward, every program is governed by an explicit prerequisite chain. A program is not implementation-ready merely because its name appears earlier in the roadmap.

The standard lifecycle is:

```text
PREREQUISITES
    ↓
DISCOVERY / DESIGN
    ↓IMPLEMENTATION
    ↓
TEST / FAILURE VALIDATION
    ↓
PRODUCTION ACCEPTANCE
    ↓
DOCUMENTATION / STATE UPDATE
    ↓
UNLOCK NEXT DEPENDENT GATE
```

A later feature must not be implemented by bypassing a missing prerequisite merely because the feature is attractive or easy to prototype.

### Global dependency rules

1. Telegram transport changes precede Telegram-heavy product expansion.
2. Durable state/events precede intelligence projections that depend on them.
3. Intelligence schemas precede source-specific intelligence adapters.
4. Dataset discovery and lineage precede large external-dataset integration.
5. Source selection precedes forking/retaining authoritative external datasets.
6. Canonical schema mapping precedes cross-dataset correlation.
7. Evidence/provenance precedes high-confidence correlation.
8. IntelGraph precedes full correlation and case fusion.
9. Media extraction precedes media-derived intelligence.
10. Command contracts precede large-scale command ecosystem expansion.
11. Plugin compatibility contracts precede serious third-party ecosystem claims.
12. Release/operations gates remain mandatory after every major integration.

---

# 37. Program-by-program prerequisite matrix

| Program | Prerequisites before implementation | Primary gate/output |
|---|---|---|
| A — Telegram Core | current Telegram facade, current error/rate paths, plugin call-path audit | `TG-*` governed transport |
| B — Telegram State | A transport control, current entity/dialog model, durable DB migrations | `STATE-*` durable state/cache |
| C — Telegram Events | B state model, event normalization contract, SQLite/WAL event schema | `EVENT-*` durable/replayable events |
| D — Archive | A+B+C, bounded media workspace, JobEngine, FTS5/search contracts | `ARCH-*` resumable archive |
| E — UX/Product | command inventory, Command Contract, Telegram traffic control, permission model | `UX-*` coherent product surface |
| F — AI | AI service/provider abstraction, context bounds, JobEngine, command contracts | `AI-*` unified advisory AI |
| G — Automation | Event Engine, JobEngine, command/action authorization, durable state | `AUTO-*` durable workflows |
| H — IntelGraph | event/observation concepts, source/provenance schema, canonical entity model | `INTEL-*` intelligence substrate |
| I — IOC | H foundation, normalization rules, extraction tests | `IOC-*` deterministic indicators |
| J — TGINTEL | A+B+C+H, explicit Telegram observation scope | `TGINTEL-*` Telegram intelligence |
| K — Identity | H+I, source registry, evidence/confidence model | `USER-*` bounded identity pivots |
| L — Domain | H+I, central HTTP/network service, public-source adapters | `DOMAIN-*` infrastructure graph |
| M — Links | I+L, HTTP resource policy, URL normalization | `LINK-*` link graph |
| N — Media | D, Media service, isolation, hashing/OCR/STT availability | `MEDIAINTEL-*` media evidence |
| O — Cases | H+I+correlation inputs+timeline primitives | `CASE-*` investigations |
| P — Security | I+M+L, bounded network policy | `SEC-*` defensive intelligence |
| Q — Git | H+I, public Git provider adapter and provenance | `GIT-*` public-code intelligence |
| R — Plugin ecosystem | Command Contract, service interfaces, permissions, compatibility metadata | `SDK-*` stable plugin API |
| S — Competitive catch-up | feature matrix, command inventory, test evidence | `COMP-*` verified parity |
| T — Release/Operations | every preceding feature's tests/metrics/migrations | production acceptance |

This matrix is a dependency contract, not a promise that all programs execute linearly. Independent work may proceed in parallel only when its prerequisites are already satisfied.

---

# 38. Intelligence foundation expansion — Source Registry + Evidence Model

The intelligence side of Astra now explicitly includes a source registry beneath IntelGraph.

## 38.1 Canonical intelligence entities

The canonical entity layer may represent:

- person;
- organization;
- Telegram account;
- Telegram chat/channel;
- username;
- phone-like indicator;
- email;
- domain;
- IP/ASN;
- URL;
- hash;
- file/media;
- message;
- dataset;
- dataset family;
- source;
- event;
- case;
- location;
- unknown entity.

## 38.2 Observation model

Every imported intelligence observation should be traceable to:

```text
observation_id
entity_id
source_id
source_family
source_dataset
source_version
retrieved_at
observed_at
query/context
matched_field
match_type
confidence
provenance
```

## 38.3 Evidence states

Use explicit states:

- `OBSERVED`
- `DERIVED`
- `CORRELATED`
- `INFERRED`
- `UNKNOWN`
- `CONTRADICTED`

AI and correlation layers must preserve these states rather than flattening them into a single “truth” field.

---

# 39. New intelligence subsystem — Intel Dataset Lineage Engine

Astra will not treat every external dataset repository as an independent intelligence source.

The objective is:

> **maximize genuinely unique intelligence coverage while collapsing duplicate and derived copies.**

This is a discovery/lineage problem first and a query-engine problem second.

## 39.1 What this subsystem does

The Dataset Lineage Engine determines:

- which repositories belong to the same dataset family;
- which repositories are duplicates;
- which are derived copies;
- which are subsets;
- which are re-indexed/reformatted versions;
- which are merged/composite datasets;
- which appear independent;
- which are plausible master/root candidates;
- how much unique coverage each family contributes.

## 39.2 Classification model

The primary lineage classification is:

- `MASTER_CANDIDATE`
- `VERSION`
- `DERIVED`
- `DUPLICATE`
- `SUBSET`
- `MERGED`
- `INDEPENDENT`
- `UNKNOWN`

The classification is about **data lineage**, not about whether the dataset is interesting or sensitive.

### Important rule

Sensitivity must not be used as a dataset-discovery filter.

A dataset can therefore simultaneously be:

```text
MASTER_CANDIDATE
+ unique lineage
+ high coverage
+ sensitive
```

and still remain in the lineage/corpus inventory.

Operational handling of sensitive information is a separate policy dimension and must not distort lineage analysis.

---

# 40. Dataset intelligence prerequisite gate — complete the census first

Before implementing the Hugging Face dataset query layer in Astra, complete the external dataset census.

This is a hard prerequisite.

## DS-0 — Account discovery

Inventory every supplied account and then expand to related public dataset references where useful.

Current known account set from the research phase includes:

- `greyexploiter`
- `tfqdeadlo`
- `PhisherJR`
- `Kzr0xx`
- `Bruhletme`
- `sauravsingh2111`
- `warmifans`

For each account record:

- account identity;
- datasets;
- Spaces/APIs;
- models that reference datasets;
- linked dataset families;
- visible repository relationships;
- activity/history useful for lineage.

**Exit:** every supplied account has a machine-readable inventory.

## DS-1 — Dataset inventory

For every discovered dataset collect metadata before downloading large content:

- repository ID;
- provider;
- dataset name;
- file list;
- formats;
- file sizes;
- row counts when available;
- schema/columns;
- data types;
- partitions;
- indexes;
- README/documentation;
- commit history;
- creation/update history;
- linked Spaces/APIs;
- known source declarations;
- related repositories.

**Exit:** all candidate datasets have normalized metadata records.

## DS-2 — Dataset family clustering

Group repositories that appear to originate from the same underlying corpus.

Examples of families discovered during research include large HITECH/ICMR/India-data/Telegram-style families. The family label is provisional until lineage analysis confirms it.

**Exit:** every dataset is assigned to a provisional family or `UNKNOWN`.

## DS-3 — Duplicate detection

Use progressively stronger evidence:

### Level 1 — metadata

Compare:

- row count;
- total size;
- schema;
- partition layout;
- file naming;
- index structure.

### Level 2 — file identity

Where accessible, compare:

- SHA-256/file hashes;
- exact file sizes;
- Parquet metadata;
- row-group statistics.

### Level 3 — schema fingerprint

Normalize:

- column names;
- column order;
- data types;
- nullable structure.

### Level 4 — controlled content fingerprints

Use bounded samples/record fingerprints rather than blindly downloading hundreds of GB.

### Level 5 — overlap evidence

Where legitimate remote query access exists, compare controlled record samples and stable fingerprints.

**Exit:** likely duplicates are clustered and no longer counted as independent sources.

## DS-4 — Derived/subset detection

Determine whether one source is:

- cleaned from another;
- reformatted from another;
- re-indexed from another;
- a temporal/version copy;
- a subset;
- an extracted partition;
- an enrichment of another;
- a partial mirror.
A smaller dataset is not automatically discarded. It may contain unique records or a useful partition not present in the selected master.

**Exit:** derived/subset relationships are represented explicitly.

## DS-5 — Merge/composite detection

Identify repositories that combine multiple source families.

Example:

```text
A + B → composite C
```

Composite datasets must retain both parent lineage and additive coverage information.

**Exit:** merged sources are not incorrectly classified as independent originals.

## DS-6 — Master/root candidate detection

Rank master candidates using:

- coverage;
- chronology;
- provenance;
- schema completeness;
- source declarations;
- commit history;
- record overlap;
- partition structure;
- index structure;
- version relationships.

**Largest does not automatically mean master.**

The result is a confidence-ranked master candidate, not an unsupported claim of original ownership.

**Exit:** every important family has one or more master candidates with reasons.

## DS-7 — Source lineage graph

Represent lineage as a graph:

```text
                    MASTER CANDIDATE
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          VERSION        SUBSET        DERIVED
             │             │             │
             ▼             ▼             ▼
           FORK          INDEXED       CLEANED
             \             │             /
              \            ▼            /
               └─────── MERGED ───────┘
```

Each repository becomes a node with lineage edges.

**Exit:** source families can be traversed from root candidates to descendants.

## DS-8 — Unique coverage analysis

For each family calculate/estimate:

- repositories discovered;
- master candidates;
- duplicates;
- derived copies;
- subsets;
- merged/composite sources;
- independent sources;
- unknown lineage;
- estimated unique coverage;
- duplicate volume;
- lineage confidence.

**Exit:** we know which repositories materially add information.

## DS-9 — Fork/retain decision

Only after DS-0 through DS-8:

```text
account census
    ↓
dataset inventory
    ↓
family clustering
    ↓
duplicate analysis
    ↓
derived/subset analysis
    ↓
merged-source analysis
    ↓
master candidates
    ↓
unique coverage
    ↓
SELECT AUTHORITATIVE SOURCES
    ↓
fork/retain selected sources
    ↓
freeze source manifest
```

Do not build Astra's query adapters around random duplicate forks before this gate passes.

**Exit:** a deliberately selected set of source repositories/families is frozen for implementation.

## DS-10 — Canonical source manifest

Create a machine-readable manifest with fields such as:

```yaml
source_family: <family>
master_candidates:
  - repository: <repo>
    confidence: <score>
derived: []
duplicates: []
subsets: []
merged: []
independent: []
coverage:
  estimated_unique: <value>
query_methods:
  - dataset_viewer
  - remote_parquet
  - api
lineage_confidence: <score>
```

This manifest becomes the source-of-truth for external intelligence integration.

---

# 41. Hugging Face implementation gate — only after dataset census

After DS-0 through DS-10 passes, implement the actual remote intelligence layer.

## HF-1 — Remote source registry

Create a registry of selected sources, not an unbounded list of every discovered fork.

Conceptual components:

```text
SourceRegistry
DatasetAdapter
SchemaMapper
QueryPlanner
RemoteQueryExecutor
ResultNormalizer
ProvenanceRecorder
SensitiveDataPolicy
ResultCache
IntelGraphIngestor
```

## HF-2 — Remote-first querying

Prefer remote querying for large sources where supported.

Do not automatically download multi-hundred-GB/billion-row datasets to the laptop merely to make them searchable.

The adapter should choose among legitimate available transports such as:

- public dataset viewer/query interfaces;
- remote Parquet access where supported;
- an explicitly provided public query API/Space;
- other documented remote interfaces.

## HF-3 — Canonical schema mapping

Map source-specific fields into Astra's canonical entity/indicator schema.

Examples:

```text
mobile / phone / phoneNumber / msisdn → PHONE
email / mail / emailAddress          → EMAIL
username / handle                    → USERNAME
name / full_name                     → NAME
address / location                   → ADDRESS
```

Mappings must retain original field names for provenance.

## HF-4 — Provenance

Every result must retain, where available:

- source ID;
- dataset ID;
- dataset version;
- source family;
- record/row identifier;
- retrieval timestamp;
- query;
- matched field;
- match type;
- confidence;
- lineage relationship.

## HF-5 — Lineage-aware result aggregation

If five repositories are derived from the same master family, Astra must not present them as five independent confirmations.

The result layer should say, conceptually:

```text
5 repositories
1 source family
1 lineage cluster
```

and score evidence accordingly.

## HF-6 — Remote result caching

Cache only the minimum useful metadata/result evidence required for repeatability and local search. Avoid turning Astra into an uncontrolled mirror of every remote dataset.

## HF-7 — IntelGraph ingestion

Normalized observations flow into IntelGraph with source lineage intact.

**Exit:** selected external datasets become queryable intelligence sources without sacrificing provenance or wasting local storage on redundant copies.

---

# 42. Remote intelligence source framework

The Hugging Face layer is one implementation of a broader source framework.

Future source types should plug into the same contracts:

```text
Telegram source
Web source
Domain source
Git source
Dataset source
Media source
Public API source
Local archive source
        ↓
SourceRegistry
        ↓
Adapter
        ↓
Normalizer
        ↓
Provenance
        ↓
IntelGraph
```

This prevents every OSINT provider from becoming an isolated plugin with incompatible schemas.

---

# 43. Dataset intelligence commands

The final user-facing surface should expose dataset intelligence without requiring knowledge of internal source IDs.

Potential commands:

- `.intel sources`
- `.intel source <id>`
- `.intel source family <id>`
- `.intel source lineage <id>`
- `.intel source coverage <id>`
- `.intel search <indicator>`
- `.intel investigate <indicator>`
- `.intel graph <entity>`
- `.intel timeline <entity>`
- `.intel evidence <entity>`
- `.intel export <case>`

Exact names remain subject to Command Contract collision review.

---

# 44. Intelligence correlation architecture

The final intelligence flow is:

```text
Telegram
Web / Domain
Public Code
Media / OCR / STT
Selected External Datasets
Local Archive
        │
        ▼
Source Registry        │
        ▼
Normalization
        │
        ▼
Entity Resolution
        │
        ▼
Evidence / Provenance
        │
        ▼
IntelGraph
        │
        ▼
Correlation Engine
        │
 ┌──────┼──────────┐
 ▼      ▼          ▼
IOC   Timeline    Cases
 │      │          │
 └──────┼──────────┘
        ▼
AI-assisted analysis / reporting
```

The graph is storage/foundation. Correlation is an explicit execution layer. Timeline and Cases are durable projections of evidence and relationships.

---

# 45. Unified Search + Entity Inspector dependency

Unified search and `.inspect` must not become isolated convenience commands.

## SEARCH prerequisites

Before `SEARCH-*` cross-domain implementation:

1. source schemas exist;
2. local FTS/search contracts exist;
3. IntelGraph observation model exists;
4. archive/event projections exist;
5. provenance fields exist;
6. result ranking/bounds are defined.

## INSPECT prerequisites

Before `INSPECT-*`:

1. canonical target classifier;
2. source registry;
3. intelligence engine registry;
4. evidence model;
5. bounded result aggregation;
6. correlation engine contract.

Then:

```text
.inspect target
    ↓
classify target
    ↓
dispatch relevant engines
    ↓
retrieve bounded evidence
    ↓
correlate
    ↓
show concise result
    ↓
drip into source/evidence records
```

---

# 46. Command Contract is a universal prerequisite for scale

The existing competitive addendum defines the Command Bus/Command Contract. This roadmap now treats it as a prerequisite for broad product expansion rather than a late cleanup task.

Every new command should declare:

- canonical name;
- aliases;
- argument schema;
- description;
- category;
- permissions;
- operation class;
- priority;
- resource limits;
- timeout;
- cancellation support;
- durable/non-durable behavior;
- confirmation requirements;
- network usage;
- destructive-effect classification;
- owner plugin/version.

This prevents the growing feature surface from turning into command collisions or undocumented behavior.

---

# 47. Control-plane prerequisite model

The Control Plane remains an in-process coordination/observation model, not a new service.

Its prerequisite chain is:

```text
Command Contract
+ JobEngine
+ TelegramTrafficController
+ Event Engine
+ IntelGraph
+ Media/Search services
        ↓
Control Plane projections
        ↓
.status / .health / .jobs / .plugins / .telegram / .intel / .media / .storage
```

The control plane must never become a second storage authority or a second workflow engine.

---

# 48. Full Astra 2.x dependency graph

The detailed implementation order is now:

```text
CURRENT v1.0.0 BASELINE
        │
        ▼
A — Telegram Core 2.0
        │
        ▼
B — Telegram State Engine
        │
        ▼
C — Telegram Event Engine
        │
        ├───────────────────────┐
        ▼                       ▼
D — Archive Engine        H0 — IntelGraph Foundation
        │                       │
        ▼                       ▼
E — Command/UX foundation I — IOC foundation
        │                       │
        ├──────────────┬────────┘
        ▼              ▼
G — Automation    DATASET CENSUS / LINEAGE
                       │
                       ▼
              MASTER SOURCE SELECTION
                       │
                       ▼
                HF / REMOTE SOURCES
                       │
                       ▼
        J/K/L/M/Q — intelligence sources
                       │
                       ▼
                 N — Media Intel
                       │
                       ▼
              CORRELATION ENGINE
                       │
                       ▼
               O — Timeline/Cases
                       │
              ┌────────┴────────┐
              ▼                 ▼
        F — AI 2.0          P — Security
              │                 │
              └────────┬────────┘
                       ▼
                 R — Plugin SDK
                       │
                       ▼
                 S — Competitive
                       │
                       ▼
                 T — Operations
```

This does not delete or invalidate the original A–T programs. It makes the dependencies explicit so implementation does not outrun the architecture.

---

# 49. Intelligence dataset selection policy

For the dataset-discovery phase, the primary optimization objective is **unique information coverage**, not dataset count.

Therefore:

- duplicate repositories should collapse into one lineage cluster;
- derived repositories remain recorded but should not be counted as independent sources;
- subsets are retained when they add unique coverage or useful queryability;
- merged datasets retain all parent lineage;
- independent datasets remain separate source families;
- uncertain relationships remain `UNKNOWN` until evidence improves;
- the largest dataset is only a master candidate until lineage evidence supports it.

The dataset corpus should therefore be described as:

```text
repositories discovered
→ source families
→ master candidates
→ unique coverage
```

rather than simply:

```text
number of repositories
```

---

# 50. Sensitive-data handling is a separate operational dimension

The dataset-lineage objective is not to discard sources because their contents are sensitive. Dataset discovery, deduplication and lineage analysis operate independently from the later operation policy layer.

The operational layer may still need to know:

- what class of data an operation would expose;
- whether a query can return raw records;
- whether output should be minimized/redacted;
- what authorization context applies;
- whether the operation is permitted by Astra's policy.

These controls do **not** determine whether a dataset is unique, a master candidate, derived or duplicated.

This separation is intentional:

```text
DATASET DISCOVERY
    ↓
What exists?
What is unique?
What is derived?
What is the master candidate?

OPERATION POLICY
    ↓
What can this operation expose?
What output is appropriate?
What authorization applies?
```

---

# 51. Intelligence quality rules

Astra's intelligence quality should be measured by evidence quality, not by raw result count.

### Rule 1 — provenance first

Every meaningful result should have a source and observation timestamp.

### Rule 2 — lineage-aware corroboration

Multiple copies of one source family do not equal multiple independent confirmations.

### Rule 3 — correlation is not identity

A shared username, address fragment, image similarity or other weak signal is not automatically proof of identity.

### Rule 4 — contradictions are first-class

Conflicting observations must be retained and surfaced rather than silently overwritten.

### Rule 5 — unknown is valid

The system must be able to say `UNKNOWN` rather than manufacture certainty.

### Rule 6 — AI is advisory

AI may explain evidence and propose hypotheses, but the durable graph stores the evidence and provenance, not the model's unsupported conclusion.

---

# 52. New acceptance gates for the intelligence corpus

The intelligence corpus is not production-ready until all of these are satisfied:

### `DS-ACCEPT-1` — Census complete

All supplied external accounts and discovered datasets have normalized inventory records.

### `DS-ACCEPT-2` — Lineage map complete

Major families have duplicate/derived/subset/merged/master-candidate relationships.

### `DS-ACCEPT-3` — Unique coverage measured

The corpus can distinguish repository count from estimated unique coverage.

### `DS-ACCEPT-4` — Source manifest frozen
Selected sources and their lineage are recorded in a versioned manifest.

### `DS-ACCEPT-5` — Remote query validated

Each selected source has a documented query mechanism and bounded failure behavior.

### `DS-ACCEPT-6` — Provenance verified

Astra can trace a returned observation back to source family/dataset/version/query context.

### `DS-ACCEPT-7` — Graph ingestion verified

Normalized observations enter IntelGraph without losing lineage.

### `DS-ACCEPT-8` — Duplicate corroboration suppressed

The same underlying source family is not incorrectly counted as independent corroboration.

---

# 53. What happens when a new dataset is discovered later

A new dataset must not immediately become a new Astra source.

Its lifecycle is:

```text
NEW DATASET
    ↓
metadata inventory
    ↓
family candidate
    ↓
lineage comparison
    ↓
duplicate / derived / subset / merged / independent
    ↓
coverage delta
    ↓
source selection decision
    ↓
manifest update
    ↓
adapter enablement
```

If it adds no unique coverage and is merely a duplicate, it remains a lineage record rather than becoming another query target.

If it adds unique records, a unique partition, a new independent family or a materially better query interface, it may be promoted into the active source set.

---

# 54. Zero-cost intelligence architecture

The intelligence platform must remain compatible with the project's ₹0/$0 constraint.

Prefer:

- public/free data interfaces;
- public GitHub metadata;
- public DNS/RDAP/CT sources;
- local SQLite/FTS5;
- local caching;
- open-source parsers;
- local processing;
- free/public remote query interfaces where legitimately available.

No intelligence capability may become dependent on a paid provider simply because it is convenient.

Provider-specific integrations must remain replaceable adapters.

---

# 55. Final roadmap execution rule

**Do not code ahead of the dependency graph.**

If the next feature requires a missing contract, build the contract first.

If the next intelligence feature requires a missing source lineage map, complete the lineage map first.

If a dataset family has ten apparent repositories, do not integrate all ten before determining whether they are one underlying source.

If a master candidate has not been established, keep the source provisional.

If a correlation has no explainable evidence, keep it uncertain.

If a feature is durable, build its recovery path with it rather than adding recovery later.

If a feature adds Telegram traffic, route it through the TelegramTrafficController rather than creating another rate-control path.

This is the governing principle for the remainder of AstraUserbot 2.x:

> **Discover → normalize → verify lineage → select authoritative sources → implement → correlate → prove → release.**

---

**Roadmap objective remains unchanged:** make AstraUserbot one coherent, feature-rich, zero-cost Telegram automation and local intelligence platform without sacrificing the production-grade engineering foundation already achieved in v1.0.0. The new dataset lineage and prerequisite model expands the roadmap; it does not remove or invalidate any existing A–T capability.


---

# 56. Competitive Product-Surface Maturity — selective parity, not command-count cloning

This section is a deliberate product-surface expansion derived from research into mature Telegram userbot ecosystems, including Hikka, CatUserbot, Ultroid, CipherElite and Project Akasha. It is not a request to copy their command volume or their implementation architecture.

The objective is to copy the things that make a mature userbot feel finished:

- discoverable;
- obvious;
- interactive;
- easy to configure;
- easy to install;
- easy to operate;
- useful immediately after first launch;
- consistent across plugins;
- pleasant for both simple commands and long-running jobs.

Astra must absorb these qualities while preserving its own platform contracts:

Command Contract → authorization → TelegramTrafficController → plugin/service → JobEngine when durable → event/search/intelligence projections → evidence/provenance → recovery

No competitor-derived UX feature may bypass those contracts.

## 56.1 Research signals

### Hikka

Hikka is the strongest reference for developer-oriented userbot UX and module ergonomics. Its public documentation exposes inline forms, galleries, lists, inline interactions, bot interactions, InlineLogs, Grep, entity caching, API flood protection, UI/UX improvements and compatibility with older module ecosystems. These are product-surface patterns worth reproducing selectively.

Astra should learn from Hikka:

- richer interactive UI;
- forms;
- galleries;
- lists;
- command discovery;
- module UX;
- actionable error presentation;
- plugin/module compatibility ergonomics;
- operator-friendly diagnostics.

Astra must not copy Hikka's legacy architecture or treat old module compatibility as a reason to weaken current safety contracts.

### CatUserbot

CatUserbot is a useful reference for practical Telegram utility and group-management breadth. Its long-lived Telethon codebase and large community/plugin history demonstrate the value of immediately useful moderation and owner utilities rather than only intelligence features.

Astra should learn from CatUserbot:

- mature moderation workflows;
- practical Telegram utilities;
- purge/restriction workflows;
- useful group-management helpers;
- media helpers;
- plugin ergonomics;
- straightforward deployment/documentation.

Astra must keep destructive operations bounded, authorized and observable. Features associated with spam, raid behavior, restriction evasion or abusive automation are not competitive requirements.

### Ultroid

Ultroid is a useful reference for pluggable Telegram breadth and addon ergonomics. Its public ecosystem separates core functionality from plugins/addons and provides simple decorator-based extension patterns.

Astra should learn from Ultroid:

- clean plugin/addon discovery;
- low-friction extension conventions;
- practical moderation and utility workflows;
- media helpers;
- assistant-oriented plugin separation;
- simple examples for third-party contributors;
- predictable command ownership.

Astra's plugin API remains richer and more explicit than a simple decorator contract because it must carry permissions, operation class, resource bounds, compatibility, network usage, destructive classification and durable behavior.

### CipherElite

CipherElite is the strongest reference for frictionless product onboarding and operator experience. Its public surface emphasizes a free deployer flow, plugin discovery, AI assistant features, configuration/update controls, analytics and a large plugin/command catalog.

Astra should learn from CipherElite:

- frictionless first-run experience;
- plugin discoverability;
- AI assistant UX;
- update/configuration UX;
- deployment/operator UX;
- obvious setup diagnostics;
- easy recovery/restart controls;
- useful defaults.

Astra must not copy unsafe automatic dependency installation blindly. Plugin dependencies should remain declared, inspected, compatibility-checked and subject to Astra's controlled installation/isolation policy.

### Project Akasha / AI-oriented userbot ecosystems

AI-oriented userbots demonstrate the value of:

- context-aware AI;
- conversational automation;
- media + AI integration;
- voice/TTS workflows;
- AI-assisted Telegram interaction;
- persistent conversational context.

Astra should learn from this product behavior while keeping the AI advisory boundary:

- model output is not authorization;
- model output is not durable truth;
- tool access is explicitly bounded;
- destructive actions require policy/authorization;
- durable work goes through JobEngine;
- context is bounded and provenance-aware.

## 56.2 Cross-ecosystem product qualities

Across the researched ecosystems, Astra should deliberately converge on:

### Help and discovery

The owner should not need to remember command names.

Required direction:

- polished .help;
- category browsing;
- search by command name/description;
- aliases;
- examples;
- permissions;
- operation class;
- owning plugin;
- whether a command creates a durable job;
- whether network access is required;
- whether confirmation is required.

Target interaction:

.help → categories

.help moderation → moderation commands

.help search → matching commands

.command describe <name> → complete contract

.command examples <name> → runnable examples

### Obvious commands

Commands should use predictable names and aliases.

Avoid:

- cryptic abbreviations unless historically established;
- multiple plugins claiming the same canonical command;
- undocumented hidden aliases;
- commands whose destructive behavior is not obvious.

The Command Contract becomes the source of truth.

### Predictable aliases

Aliases must be:

- explicit;
- collision-checked;
- versioned;
- shown in help;
- included in compatibility metadata.

An alias must never bypass permissions or operation classification.

### Discoverability

Users should be able to discover functionality from inside Telegram.

Target capabilities:

- command search;
- plugin/category browsing;
- examples;
- recently used commands where privacy-safe;
- contextual suggestions after known errors;
- links from a command to its plugin/source/contract;
- discoverable job status/retry/cancel controls.

### Useful defaults

A fresh installation should work sensibly before extensive configuration.

Defaults should cover:

- safe help;
- health/status;
- plugin inventory;
- bounded diagnostics;
- standard formatting;
- conservative Telegram traffic limits;
- safe media limits;
- bounded AI context;
- local storage paths;
- default logging;
- recovery visibility.

Defaults must be conservative. Convenience must not silently enable destructive or high-volume behavior.

## 56.3 Rich interactive UI

Astra should reach a mature interactive UX without making interactive UI mandatory.

### UX-UI-1 — Buttons

Support inline buttons for:

- pagination;
- navigation;
- confirmation;
- retry;
- cancel;
- open details;
- source/evidence inspection;
- case navigation;
- plugin/category navigation.

### UX-UI-2 — Forms

Provide structured forms for commands with multiple parameters.

Examples:

- automation rule creation;
- archive scope;
- AI context selection;
- case creation;
- dataset/source inspection;
- moderation configuration.

Forms must produce the same Command Contract as text commands.

### UX-UI-3 — Galleries

Support bounded galleries for:

- media search;
- image results;
- archived media;
- screenshots;
- evidence media;
- case attachments.

Every gallery must enforce result count, media-size and resource limits.

### UX-UI-4 — Lists

Support interactive lists for:

- plugins;
- commands;
- cases;
- jobs;
- sources;
- entities;
- datasets;
- lineage families;
- evidence records.

### UX-UI-5 — Progress

Long-running operations should expose:

- queued;
- running;
- progress;
- waiting;
- completed;
- failed;
- recovery required.

Where Telegram edits are too expensive, use bounded progress updates rather than message spam.

### UX-UI-6 — Structured errors

Errors should answer:

1. what failed;
2. whether the operation changed anything;
3. whether retry is safe;
4. what the user can do next;
5. where detailed diagnostics live.

Never expose secrets, internal stack traces or provider credentials.

## 56.4 Module/plugin UX

Astra's plugin system should feel as easy to use as the mature ecosystems while remaining safer.

### PLUX-1 — Plugin catalog

Expose:

.plugins

with:

- installed;
- running;
- quarantined;
- disabled;
- incompatible;
- available metadata;
- version;
- capabilities;
- permissions;
- network usage;
- dependencies;
- compatibility.

### PLUX-2 — Plugin detail

Target:

.plugin <name>

Show:

- purpose;
- commands;
- aliases;
- services used;
- permissions;
- network access;
- durable jobs;
- configuration;
- dependencies;
- compatibility;
- source;
- version;
- safety classification.

### PLUX-3 — Plugin lifecycle

Support controlled:

- enable;
- disable;
- reload where safe;
- quarantine;
- update;
- rollback;
- compatibility validation.

Plugin lifecycle actions must not corrupt active jobs or durable state.

### PLUX-4 — Plugin installation ergonomics

Astra should eventually support a clear workflow:

discover → inspect → compatibility check → dependency check → policy check → install → load → health check → enable

Do not implement blind:

plugin asks for dependency → pip install immediately

Third-party code remains an untrusted edge.

## 56.5 Moderation product maturity

Astra already has moderation foundations. The goal is to make them feel complete rather than merely increase command count.

Required workflow quality:

- target selection from reply/username/ID;
- permission preflight;
- capability preflight;
- confirmation for dangerous bulk operations;
- bounded target count;
- progress;
- audit record;
- result summary;
- retry/recovery classification;
- clear partial-success reporting.

Target workflows:

- purge;
- ban/unban;
- mute/unmute;
- warn;
- kick;
- pin/unpin;
- lockdown;
- anti-spam;
- filters;
- welcome/goodbye;
- moderation reports;
- moderation history.

Do not add unrestricted spam/raid automation merely for parity with old userbot ecosystems.

## 56.6 Practical Telegram utilities

Expand the utility surface around high-frequency owner tasks:

- message inspection;
- message IDs;
- permalink generation;
- entity inspection;
- chat diagnostics;
- reply/reference helpers;
- formatting;
- notes/bookmarks;
- saved-message workflows;
- templates/snippets;
- translation;
- extraction;
- link inspection;
- bounded bulk operations;
- local search;
- archive search;
- job controls.

Every utility should prefer reusing existing services rather than creating a duplicate implementation.

## 56.7 Media product maturity

The mature-userbot baseline should include convenient media workflows:

- image/media inspection;
- conversion;
- compression under explicit limits;
- metadata extraction;
- screenshot/frame extraction;
- OCR;
- speech-to-text;
- text-to-speech;
- media search;
- media deduplication;
- archive/export;
- evidence attachment.

The media intelligence pipeline remains authoritative for hashes, OCR/STT evidence and correlation. UX commands should be thin adapters over that platform.

## 56.8 AI assistant UX

Astra's AI should feel as easy to use as modern AI-oriented userbots while remaining safer.

Required UX patterns:

- reply to a message → ask AI about it;
- selected message window → summarize/explain;
- media → OCR/STT → AI;
- archive/search result → AI synthesis;
- intelligence evidence → AI explanation;
- case/timeline → AI-assisted report draft;
- conversational follow-up within bounded context;
- explicit model/provider status;
- clear failure/retry behavior.

Target flow:

Telegram context → bounded context builder → AI provider → structured result → optional durable job → evidence/provenance

AI must never silently mutate Telegram state.

## 56.9 Context-aware conversational automation

Support controlled conversational workflows:

- conversation context windows;
- per-chat context policies;
- explicit reset;
- context size limits;
- local context cache;
- source-aware context;
- media-derived context;
- job-backed long conversations where necessary.

Automation may propose actions, but actual Telegram mutations still pass through authorization and traffic-control layers.

## 56.10 Update/configuration UX

A mature Astra installation should make lifecycle management obvious.

Target:

.update
.config
.restart
.health
.doctor

Features:

- show current version;
- show available update;
- preflight compatibility;
- display changed components;
- preserve configuration;
- preserve durable state;
- refuse unsafe migrations;
- support rollback/recovery;
- report exact post-update health.

Updates must never silently replace the durable database or invalidate active jobs.

## 56.11 Deployment/operator UX

Astra is local-first, but local-first does not mean difficult.

First-run should provide:

1. environment preflight;
2. dependency check;
3. Telegram credential/session guidance;
4. storage initialization;
5. plugin discovery;
6. AI provider status;
7. isolation availability;
8. systemd/service guidance;
9. health verification;
10. first safe command tutorial.

Target:

clone → configure → preflight → initialize → login → health → .help → ready

No paid hosting is required.

Optional deployment helpers must remain replaceable and must not become architectural dependencies.

## 56.12 Easy installation

Installation documentation should be optimized for the shortest safe path.

Provide:

- one canonical local install path;
- one canonical development/test path;
- one canonical systemd path;
- explicit zero-cost assumptions;
- exact prerequisites;
- common failure diagnostics;
- safe update path;
- backup/recovery path.

Avoid maintaining many stale deployment paths merely because old userbots used them.

## 56.13 Product-surface acceptance gates

Add these gates to the roadmap execution:

### UX-MATURITY-1 — Command discovery

Every production command is discoverable from the command registry and searchable through help.

### UX-MATURITY-2 — Interactive foundation

Buttons, pagination, confirmations and progress are available through shared UX services.

### UX-MATURITY-3 — Forms/galleries/lists

High-value workflows expose structured UI where it materially improves usability.

### UX-MATURITY-4 — Plugin UX

Plugins have inspectable metadata, lifecycle state, compatibility and source information.

### UX-MATURITY-5 — Moderation maturity

High-frequency moderation workflows have preflight, authorization, bounds, audit and recovery semantics.

### UX-MATURITY-6 — AI UX

AI works naturally with replies, bounded context, media and local intelligence while preserving advisory authority.

### UX-MATURITY-7 — Lifecycle UX

Update/configuration/restart/doctor workflows are deterministic and recoverable.

### UX-MATURITY-8 — First-run UX

A clean installation can reach a healthy state through one documented, zero-cost path.

### UX-MATURITY-9 — Product acceptance

The complete UX surface passes focused tests, full regression, production acceptance and owner-host validation.

## 56.14 Competitive catch-up rule

A competitor feature is eligible for Astra only when at least one of these is true:

- it materially improves daily Telegram use;
- it improves discoverability;
- it improves safety;
- it improves operator experience;
- it improves AI/media interaction;
- it provides a reusable platform primitive;
- it closes a clearly demonstrated product-surface gap.

Do not implement a feature solely because another userbot has more commands.

The target is:

> mature product surface, not maximal command count.

---

# 57. Roadmap completion state and deferred capabilities

The roadmap is intentionally larger than the current implementation.

The existence of a section, gate or design in this file does not mean the feature is already built.

At the current execution checkpoint:

- numbered Phases 1–10 have been completed through the Security + Ecosystem gate;
- the long-term A–T program map remains the capability architecture;
- future program work must still be implemented and accepted;
- dataset/Hugging Face work is explicitly not complete merely because the design exists.

## 57.1 Dataset/Hugging Face work remains gated

The correct sequence remains:

account census → dataset inventory → family clustering → lineage comparison → duplicate/derived/subset/merged analysis → master candidate selection → unique coverage → source manifest → remote query validation → provenance → graph ingestion

Therefore Astra must not:

- fork random datasets before lineage analysis;
- treat repository count as unique coverage;
- build adapters for every discovered fork;
- claim a master source without evidence;
- download huge datasets merely because they are available;
- treat duplicate datasets as independent corroboration.

The DS-*, DS-ACCEPT-* and HF-* gates are future implementation work until their owner-host acceptance evidence exists.

## 57.2 Other roadmap designs are also not completion claims

The same rule applies to:

- future UX maturity gates;
- remaining AI product work;
- future automation capabilities;
- additional intelligence adapters;
- expanded media workflows;
- correlation engine expansion;
- dataset integrations;
- plugin SDK expansion;
- competitive catch-up;
- release/operations work.

A feature is complete only after implementation, tests, documentation, production acceptance and owner-host validation satisfy the relevant gate.

## 57.3 Prerequisite-first execution

Before beginning any major future phase:

1. inspect the current roadmap gate;
2. identify every prerequisite;
3. verify which prerequisites are actually implemented;
4. finish missing prerequisites first;
5. perform external-source/account/dataset research where required;
6. select authoritative sources;
7. implement the minimum platform contract;
8. implement the feature;
9. integrate search/intelligence/job/event projections where applicable;
10. test failure/recovery paths;
11. update acceptance evidence;
12. only then mark the gate complete.

This prevents documentation from being mistaken for implementation.

## 57.4 No hidden completion

Never mark a gate COMPLETE because:

- code exists;
- a command appears in help;
- a test passes in isolation;
- a dataset was discovered;
- a repository was forked;
- an adapter was written;
- a README describes the feature.

Completion requires the gate's full evidence contract.

