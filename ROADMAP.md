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
19. moderation feature family
20. Telegram utility family
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
