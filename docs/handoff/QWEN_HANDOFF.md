# AstraUserbot — Comprehensive Qwen Handoff

> **Purpose:** Give a new coding/research agent enough context to work on AstraUserbot without making the owner repeat the project history. This document is a source-oriented handoff, not a claim that every planned feature is production-accepted.
>
> **Repository:** https://github.com/Exploiter69/astraUserbot  
> **Branch:** `main`  
> **Inspected:** 2026-10-16  
> **Current declared release candidate:** `1.0.1` (see `VERSION`, README and release docs). The project’s architecture and roadmap are already on the post-Phase-10/Astra 2.x path; do not assume the release number captures all current feature work.

## 0. Instructions to the receiving agent (Qwen)

You are continuing an existing, substantial Python Telegram userbot project. Do not treat it as a greenfield bot and do not replace its architecture with a new framework.

1. **Read the source before changing it.** Begin with this handoff, then read `README.md`, `docs/architecture/ARCHITECTURE.md`, `docs/architecture/PRODUCTION_BOUNDARY.md`, `docs/architecture/DATA_MODEL.md`, `docs/architecture/JOB_MODEL.md`, `docs/plugins/PLUGIN_ECOSYSTEM.md`, `docs/roadmap/ROADMAP.md`, `docs/acceptance/PRODUCT_MATURITY_ACCEPTANCE.md`, and the relevant service/plugin/tests.
2. **Treat source and tests as authority for behavior.** A roadmap item, documentation heading, command registration, isolated passing test, or feature name does not alone prove production completion.
3. **Preserve owner constraints:** zero-cost architecture (₹0/$0 target), no mandatory paid APIs/hosted services/LLM, Telegram/Telethon remains transport, Python/asyncio modular monolith, SQLite is the default durable store, and existing behavior/command compatibility should be preserved unless a reviewed migration says otherwise.
4. **Never expose or ask for secrets.** Ignore credential contents. Never print tokens, API hashes, API keys, vault plaintext, session files/session strings, private messages, or personal identifiers into logs/docs. Use redacted examples. The owner explicitly requires credentials to be ignored/not exposed.
5. **Do not claim a sandbox that is not real.** Plugin code runs in-process and is not generally process-isolated. Bubblewrap isolation exists for classified child workloads (e.g. relevant subprocess/media/eval work); only claim isolation at the boundary actually enforced.
6. **Do not bypass platform services.** Route Telegram effects through TelegramFacade/traffic policy; durable side effects through JobEngine and reconcilers; network through shared HTTP; subprocesses through the shared subprocess boundary; filesystem/media work through bounded workspace/storage services; AI through AIService; command registration through the canonical registry; plugin lifecycle through PluginManager.
7. **No blind package installation or arbitrary remote plugin installation.** Plugin install UX means safe activation of a locally discovered plugin, not arbitrary package installation.
8. **Use the release gate and test evidence.** Do not restart production, change owner-host state, or execute destructive Telegram operations merely to test. Use non-destructive tests first and request explicit owner approval for production-side effects.
9. **Update documentation and acceptance evidence with code.** Do not rewrite completed history to make progress look better. Record what was tested, where, and what was not tested.
10. **When working on the repo, favor focused, reviewable changes.** Explain assumptions, inspect dependencies, add regression tests for failure/recovery paths, run the appropriate checks, and report exact changed files and evidence.

## 1. What AstraUserbot is

AstraUserbot is a modular, service-oriented Telegram **userbot** built on Telethon. It began as a broad collection of commands and is being evolved into a reliable local-first automation, AI, media, productivity and intelligence platform.

The product is not merely a collection of Telegram command handlers. It has a shared platform core that owns lifecycle, authorization, command routing, traffic policy, persistence, durable jobs, recovery, search, AI boundaries, media workspaces, audit/observability and resource limits. Plugins are the feature edge.

**Declared principles from README and architecture:**

- Telegram is the transport layer; Telethon remains the client.
- Python + asyncio, single-process modular monolith; avoid heavy framework/microservice rewrites.
- Plugins provide features; shared services own infrastructure.
- One deterministic command registry and plugin lifecycle; collisions are rejected/observable.
- Ephemeral long-running tasks are supervised; restart-sensitive work is durable jobs.
- SQLite/WAL is the default durable local store; FTS5 is used for search.
- Cache and search state are derived/rebuildable, not authoritative.
- AI providers are replaceable; AI output is advisory and never authority.
- Side effects need authorization, bounded scope, and verification/reconciliation where practical.
- Resource use is bounded (CPU/RAM/disk/network/Telegram requests/HTTP/subprocess/jobs/media/AI context).
- Secrets must not appear in source control, diagnostics or ordinary logs.
- Isolation claims must match actual enforcement.
- No mandatory paid API, paid hosting, hosted database, or mandatory local LLM.

## 2. Repository and current footprint

Public repository: `Exploiter69/astraUserbot`, default branch `main`. At the time of inspection the repository tree contained roughly 328 entries, including core, services, plugins, docs, tests and engineering tools. There are about 55 non-`__init__.py` plugin Python modules in the tree; that is **not** the same as the active runtime plugin count because quarantined/disabled modules and lifecycle state affect what runs.

### Top-level structure

- `main.py` — process entry point, logging/redaction, startup HUD, runtime lifecycle and graceful shutdown.
- `client.py` — Telethon client construction and connection/retry configuration.
- `config.py` — validated environment configuration.
- `core/` — application bootstrap/context, central registry/router, database, errors, tasks, plugin lifecycle and capabilities.
- `core/services/` — shared application services: AI, automation, jobs, storage, cache, HTTP, subprocess, Telegram facade/traffic/state/events/archive, media, search, intelligence, cases, metrics, secrets, workspaces and related services.
- `plugins/` — command-facing feature modules.
- `helpers/` — reply/UX/HUD, rate limiting, network/shell/entity/archive/progress helpers.
- `astra/sdk.py`, `astra/sdk_generator.py`, `astra/templates/plugin/` — supported plugin API and deterministic scaffold generator.
- `tests/` — unit/contract/integration regressions, including lifecycle rollback, capability enforcement, job reconciliation, storage hardening, AI, automation, search, intelligence, archive and media.
- `tools/` — read-only audits, release acceptance, docs checks, registry generator, migration/security/media/storage/job/product maturity probes.
- `docs/architecture/` — canonical architectural contracts and decisions.
- `docs/roadmap/ROADMAP.md` — large active long-term roadmap and gate/dependency rules.
- `docs/acceptance/` — maturity/acceptance ledgers.
- `docs/operations/` — runbook, disaster recovery, failure modes and upgrade procedure.
- `docs/security/`, `docs/media/`, `docs/plugins/` — security, media and plugin contracts.
- `astra.service` — systemd unit template/example.
- `.env.example` — generated configuration reference; real `.env` is not to be shared.
- `requirements.txt` — runtime dependencies; `requirements-dev.txt` — development/test dependencies.
- `VERSION` — canonical version file.

### Runtime/dependency baseline visible in source

- Python async application.
- Telethon pinned at 1.44.0.
- aiohttp pinned at 3.14.3.
- aiosqlite pinned at 0.22.1.
- cryptography pinned at 50.0.1.
- python-dotenv pinned at 1.2.3.
- Linux/systemd deployment path; optional external tools such as FFmpeg/ffprobe, Tesseract, yt-dlp, rclone, aria2c and edge-tts are feature-dependent and must be detected rather than assumed installed.

## 3. Runtime lifecycle and architecture

### Process startup/shutdown

`main.py` changes the working directory to the repository root, creates `data/logs/`, configures console and rotating file logging, installs a secret-redaction filter, creates the Telethon client, starts and authorizes it, constructs `ApplicationContext`, starts shared services, loads plugins through the plugin loader/PluginManager, renders a startup HUD from live state, installs signal handlers and waits for Telegram disconnection. Shutdown is idempotent/locked and bounded across plugin shutdown, context/service closure and bootstrap/client teardown.

The startup HUD reports runtime state from live objects (Telegram connection, database integrity, services, running plugins, registered command count, JobEngine readiness, isolation backend and AI gateway) instead of maintaining a second hard-coded status table.

`client.py` creates a file-based Telethon session under `data/<SESSION_NAME>.session`, uses retry/reconnect settings and disables Telethon entity persistence to reduce high-frequency SQLite writes; Astra’s own entity/state caches handle that domain. Do not migrate to StringSession casually: the example config explicitly says file-session flow is the supported authentication path.

### Logical layers

1. **Transport:** Telethon client and Telegram events.
2. **Core runtime:** `ApplicationContext`, bootstrap, command registry/router, task supervision, errors, database and PluginManager.
3. **Shared services:** Telegram facade/traffic governor; storage/migrations; cache; durable JobEngine; HTTP; subprocess; filesystem/workspace; media; AI; search; intelligence/graph/correlation; cases; automation; secrets/vault; metrics/flags and event/archive/state services.
4. **Plugins:** commands and feature-specific glue. Plugins should not duplicate service infrastructure.
5. **External boundaries:** Telegram MTProto, public HTTP APIs, local binaries, optional AI providers and configured backup remotes.

### Command path

A command is registered through the canonical `core.registry.register_cmd()` (public SDK alias: `astra.sdk.register_command`). Registrations carry owner/plugin, stable ID, command names/aliases, permission, category, description, examples/usage, operation class/effect metadata, network/destructive/confirmation/durable-job flags, capability requirements, timeout/priority and compatibility metadata. The router/registry is the authority for discovery and dispatch; do not add a parallel registry.

Command registration occurs in plugin setup under plugin ownership context. Duplicate active names/aliases are rejected. Unloading a plugin removes its owned registrations and tracked resources.

### ApplicationContext and services

`ApplicationContext` is the shared dependency boundary and owns service construction/start/close. Inspect `core/context.py` and `core/services/__init__.py` before adding a service or passing dependencies around. Reuse the existing service rather than creating another engine with overlapping authority.

Key service families in the source tree:

- **Telegram:** `telegram.py`, `telegram_state.py`, `telegram_sync.py`, `telegram_traffic.py`, `telegram_events.py`, `telegram_event_journal.py`, `telegram_event_projections.py`, `telegram_event_replay.py`, `telegram_recorder.py`, `telegram_archive.py`, `telegram_archive_engine.py`.
- **Jobs/reconciliation:** `jobs.py`, `bounded_jobs.py`, and effect-specific send/edit/delete/join/upload job services.
- **Persistence and derived state:** `storage.py`, `cache.py`, `search.py`, `database.py`.
- **Network/process/media:** `http.py`, `subprocess.py`, `workspace.py`, `media.py`, `media_intel.py`.
- **AI:** `ai.py` with provider adapters/gateway integration in `plugins/ai_gateway/`.
- **Intelligence:** `intelgraph.py`, `intel_correlation.py`, `ioc.py`, `public_intel.py`, `security_intel.py`, plus case/media intelligence services.
- **Automation:** `automation.py` with durable JobEngine integration.
- **Security/operations:** `secrets.py`, `isolation.py`, `metrics.py`, `flags.py`, case services and task supervision.

## 4. Persistence, durable jobs and recovery

### Storage

SQLite/WAL is the default durable local store. Storage has versioned migrations, integrity checks, migration/checksum tracking and verified backup/restore contracts. Keep authority classes separate:

- authoritative external state (Telegram/provider state);
- observed/derived records (cache, graph observations, search index);
- durable operational state (jobs, attempts, events, audit, automation runs);
- cache state (rebuildable);
- configuration;
- secret references (never ordinary plaintext dumps).

FTS5 powers local full-text search. Search indexes and caches are derived and should be rebuildable. Retention/capacity rules apply to logs, message archives, audit events, media artifacts, HTTP cache and job history.

### JobEngine

Restart-sensitive or side-effecting work should use the existing durable JobEngine rather than an untracked task. The documented pipeline is:

`QUEUED → RUNNING → VERIFYING → COMPLETED`

with failure/cancellation/retry and `UNCERTAIN` outcomes where the external effect cannot safely be inferred. The engine has durable payloads/results, attempt/event history, leases/fencing, retry/backoff, idempotency, bounded workers, cancellation, progress, queue backpressure and restart recovery. A process exit code or successful API call is not automatically proof that the intended external effect completed.

Never retry a possibly completed external mutation blindly. Reconcile first. The same operation must have a deterministic identity/idempotency contract where possible. A lease expiring is not proof the work did not happen.

Effect-specific services include send/edit/delete/join/upload jobs and other bounded work. Archive, AI and automation should delegate execution/recovery to this engine rather than create their own durable scheduler.

### Tasks and scheduler

Ephemeral tasks are managed/supervised and shut down within bounded budgets. Restart-sensitive schedules/rules must use persisted state. Automation uses the durable JobEngine; it is not a second scheduler/workflow engine.

### Backup/recovery

Follow `docs/operations/OPERATIONS_RUNBOOK.md`, `docs/operations/DISASTER_RECOVERY.md`, `docs/operations/FAILURE_MODE_MATRIX.md` and `docs/operations/UPGRADE_PROCEDURE.md`. Preserve evidence before repair, run integrity/migration checks, verify backups/restores, and reconcile uncertain jobs after recovery. Do not run destructive production recovery procedures as a casual test.

## 5. Plugin ecosystem and SDK

### Lifecycle

A plugin is a Python module below `plugins/` with a `setup(client)` entry point and optional `shutdown(client)`. Metadata vocabulary includes:

- `plugin_name`
- `plugin_version`
- `plugin_api_version`
- `plugin_description`
- `dependencies`
- `optional_dependencies`
- `capabilities`
- `critical`

Legacy plugins use explicit deterministic defaults. Required dependencies load before dependents; unknown dependencies/cycles fail the load plan. Optional dependencies are informational. Runtime lifecycle states include discovery, loaded/running, disabled, failed import/setup and unloaded. Shutdown is bounded. Failed setup must roll back owned command registrations/resources and must not leave a partially active plugin.

Plugin enable/disable is controlled through PluginManager APIs. Disabling is rejected if running dependents need the plugin. Enabling requires dependencies to be running and refuses quarantined modules. Runtime toggles are not secretly persisted across restart.

### Hard quarantine

These four legacy modules are intentionally quarantined and must not be reactivated merely to make an old command available:

- `plugins.ai.ask`
- `plugins.ai.groq_client`
- `plugins.ai.summarize`
- `plugins.ai.transcribe`

The current AI path is the unified AI gateway under `plugins/ai_gateway/`.

### Plugin SDK

`astra/sdk.py` is a typed facade over existing core contracts, not a second registry/lifecycle/authorization system. It exposes `register_command`, plugin metadata/protocols, supported service protocols, capabilities, tracked task/job/resource helpers, and reconciliation types. The SDK has capability names such as `telegram.read`, `telegram.write`, `network.external`, `fs.read`, `fs.write`, `subprocess`, `jobs.enqueue`, `ai.remote`, `ai.local`, `vault.read`, `vault.write`. A declared capability is metadata, not proof of enforcement; enforcement happens at trusted service boundaries.

A deterministic plugin scaffold generator is now present:

```bash
python -m astra.sdk_generator create-plugin <lowercase_name>
# optional explicit replacement:
python -m astra.sdk_generator create-plugin <lowercase_name> --force
```

It stages generated files before replacing the destination and creates plugin source, package init, README and tests. Follow `PLUGIN_SDK.md`; do not invent a second plugin API.

### Plugin inventory by feature family

This is a source-tree inventory, not a guarantee that every module is enabled or healthy at runtime:

- **Admin/moderation:** `plugins/admin_ops/advanced_admin.py`, `plugins/moderation.py`.
- **Advanced utilities:** `plugins/advanced/mediaflow.py`, `plugins/advanced/osint_recon.py`, `plugins/advanced/quicknote.py`.
- **AI gateway:** `plugins/ai_gateway/ask.py`, `jobs.py`, `summarize.py`, `transcribe.py`, `unified.py`.
- **Legacy quarantined AI:** `plugins/ai/ask.py`, `groq_client.py`, `summarize.py`, `transcribe.py`.
- **Archive/automation/backup:** `plugins/archive/archive.py`, `plugins/automation.py`, `plugins/backup/cloud_backup.py`.
- **Crypto/vault/fun:** `plugins/crypto/vault.py`, `plugins/security/vault.py`, `plugins/fun/text_fx.py`.
- **Intelligence:** `plugins/intel.py`, `plugins/intelligence/media_cases.py`, `public_sources.py`, `security_intel.py`.
- **Media:** `plugins/media/aria2.py`, `autopost.py`, `ffmpeg.py`, `ocr.py`, `rclone.py`; `plugins/media_ops/speech.py`, `stream.py`, `video.py`.
- **Network OSINT:** `plugins/network_osint/dns.py`, `headers.py`, `ipinfo.py`, `portscan.py`, `speedtest.py`.
- **Productivity and Telegram:** `plugins/productivity.py`, `plugins/telegram_utils.py`.
- **Security/account tools:** `plugins/security/account_archiver.py`, `acl.py`, `ephemeral.py`, `hash.py`, `logger.py`, `passgen.py`, `pmguard.py`.
- **Identity:** `plugins/stealth/identity.py`.
- **System:** `plugins/system/afk.py`, `eval.py`, `help.py`, `jobs.py`, `ping.py`, `sysinfo.py`.
- **System/operator:** `plugins/system_ops/doctor.py`, `platform.py`, `product_surface.py`, `telegram_capabilities.py`, `telegram_sync.py`, `testall.py`, `utility_pack.py`.

## 6. User-facing command catalog

**Important:** the live registry is the canonical inventory. Commands are prefixed with `.` by default, but the prefix is configurable. This section groups command names verified in source patterns/docs; exact arguments/permissions/aliases should be obtained from live metadata and source before changing them. There are additional registrations in larger modules whose names are best inspected through the registry.

### Discovery/help

- `.help [command-or-category]` — command deck/category/single-command metadata.
- `.command search <query>`
- `.command describe <command>`
- `.command examples <command>`
- `.command category <name>`
- `.command aliases <command>`
- `.command permissions <command>`
- `.command source <command>`
- `.command recent` — privacy-safe recent command identities; do not log arguments.

The metadata surface includes category, owning plugin, permission, operation class, network/destructive/durable-job/confirmation flags, compatibility, timeout/priority, cancellation/durable execution, argument schema, examples, capability requirements and source reference where available.

### Runtime/operator/control plane

- `.health`, `.plugins`, `.tasks`, `.cache`, `.stats`, `.diagnostics`, `.search`, `.reindex`, `.flags`, `.status`, `.ops`
- `.doctor`, `.cleancache`, `.update` (the current doctor module explicitly says the in-chat updater is disabled in this build; update from project directory with diff review and restart safely).
- `.config ...`, `.restart ...` (explicit operator controls; inspect confirmation/authorization path before use).
- `.plugin` catalog; `.plugin <name>` detail; `.plugin search <query>`; `.plugin health <name>`; `.plugin enable <name>`; `.plugin disable <name>`; `.plugin reload <name>`; `.plugin install <name>` (safe local-discovered enable, not arbitrary package installation).
- `.tgcap ...`, `.tgsync ...`
- `.testall [safe|report|network|static]` — diagnostic suite; mutating commands are deliberately skipped.
- `.ping`, `.sysinfo`, `.eval ...` (eval is designed to use an isolated child-process boundary; verify current isolation availability/policy before assuming it will run).
- `.job [id]`, `.jobs [limit]`, `.cancel <id>`, `.retry <id>`.

### AI

- `.ai <prompt>`
- `.ai --last N <prompt>` — bounded recent-chat context (up to 32 messages and combined context cap documented as 24,000 characters).
- `.explain <text>`, `.rewrite <text>`, `.translate <text>`, `.extract <instruction>`, `.code <prompt>`
- `.ask <prompt>` compatibility command on the gateway path.
- `.summarize` (reply-based) and `.transcribe` (reply-based audio/voice).
- `.aijob <prompt>` — durable AI job.
- `.aidiag` — non-sensitive AI provider/budget/limits diagnostics.
- `.aiux summarize|explain|search|evidence|case|timeline|media ...` — product-integrated AI flows using existing AI/search/evidence/case/timeline/media services.
- Replying to an image can trigger bounded OCR → AI; audio/voice reply can trigger transcription → AI. OCR/STT accuracy improvements remain a documented quality follow-up, not proof of perfect extraction.

Provider options in configuration/docs include Groq, Gemini and loopback-only Ollama, subject to explicit remote-provider opt-in, request budgets, timeouts and resource limits. No AI tool/function-call authority is enabled. The model must not be given Telegram mutation authority.

### Durable automation

- `.autorule list`
- `.autorule show <id>`
- `.autorule create <id> <json-rule>`
- `.autorule enable <id>`
- `.autorule disable <id>`
- `.autorule delete <id>` (tombstone semantics, preserves run/audit history)
- `.autorule run <id>`
- `.autostatus`

Supported triggers documented: `MESSAGE_NEW`, `MESSAGE_EDIT`, `MEDIA_OBSERVED`, `SCHEDULED`, `JOB_COMPLETED`, `INTELLIGENCE_OBSERVED`, `OWNER_COMMAND`. Supported typed actions: `REPLY`, `FORWARD`, `TAG`, `INDEX`, `ARCHIVE`, `NOTIFY_OWNER`, `PLUGIN_ACTION`, `START_JOB`. Rules are declarative JSON, never executable Python or arbitrary expressions. They cannot expand their own chat/entity scope. High-impact/destructive automation is intentionally restricted.

### Telegram archive and account archive

- `.archive ...` — bounded Telegram history/media archive and local archive search; durable job, idempotency, cursor/recovery and content addressing contracts documented in `docs/TELEGRAM_ARCHIVE.md`.
- `.arch status [on|off]`, `.arch stats`, `.arch search <keyword>` — account archive/recorder surface.
- `.track add|remove|list` — tracked entity/account surface (inspect source for exact constraints).
- Interrupted archive work can be `UNCERTAIN`; verify before replaying.

### Intelligence / investigation / cases

- `.intel <action> <target> [page]` — general intelligence entry point.
- `.tgintel <target>`, `.userintel <target>`, `.domainintel <target>`, `.ct <target>`, `.linkintel <target>`, `.gitintel <target>`.
- `.secrisk <url>`, `.idn ...`, `.reputation ...`.
- `.inspect <target>` and `.correlate ...` are the post-Phase-10 unified entity-inspection/correlation UX; the old Telegram message inspector remains exposed as `.msg`/`.tginspect`.
- `.case new|list|show|graph|add|event|timeline|report|close ...`
- `.mediaintel`, `.mediasim <16-hex-prefix>`.
- IntelGraph/IOC, public source, username/entity, domain/infrastructure, link, Git/public-code and security intelligence are separate feature families, but all must reuse canonical source/evidence/identity services and provenance rules.

**Intelligence quality rules:** provenance first; lineage-aware corroboration; correlation is not identity; contradictions are first-class; unknown is valid; AI is advisory. Never fabricate sources, confidence, corroboration or identity resolution.

### Moderation/admin/group tools

Source patterns include:

- `.purge`, `.purgeme`, `.zombies`, `.promote`, `.demote`, `.slow`, `.kickme`
- `.warn`, `.warnings`, `.mute`, `.unmute`, `.ban`, `.unban`, `.pin`, `.unpin`, `.lockdown`, `.modreport`
- `.block`, `.unblock`
- `.pmpermit`, `.allow`, `.approve`, `.disallow`, `.disapprove`, `.listallowed`, `.listdisallowed`
- Identity commands: `.clone`, `.revert`, `.idbackup`
- AFK: `.afk`

These may affect real Telegram users/messages. Inspect operation class, authorization, confirmation, target scope, rate limits, audit and recovery before invoking or changing them. Never run mutating tests against a live account without explicit authorization.

### Media, downloads and conversion

- `.mediaflow [compress|extract|square|mute]`
- `.aria <url>`
- `.autopost <message>` / `.autopost rm <id>`
- `.ff <ffmpeg arguments>` (reply to media; bounded FFmpeg workbench)
- `.ocr` (reply to image; isolated Tesseract if available)
- `.rclone copy <src> <dest>` (bounded job path)
- `.tts <text>` / `.toaudio <text>`
- `.rip [audio|video|doc|best] <url>` (yt-dlp based; respect source rights and tool availability)
- `.round`, `.ss`, `.compress`, `.reverse`
- Media intelligence/cases: `.mediaintel`, `.mediasim ...`.

External binary presence is optional and must be diagnosed. Use MediaService/workspaces, bounded file sizes, cleanup, content hashing and proper isolation rather than raw arbitrary subprocess calls.

### Network/OSINT utilities

- `.dns <domain> [type]` (DoH)
- `.headers <url>`
- `.ip [ip/domain]`
- `.portscan <host> [ports]` (must remain scoped/authorized; do not expand into unauthorized scanning)
- `.speedtest`
- `.osint <username>` (public social-platform pivots)

Use shared HTTP/network policies, timeouts, response caps, safe URL validation, and explicit user scope. Avoid collecting or exposing sensitive personal data unnecessarily.

### Productivity, notes, utility and security

- Quick notes: `.qnote <tag> <text>`, `.qget <tag>`, `.qlist`, `.qdel <tag>`.
- Text effects: `.mock`, `.owo`, `.ghost`, `.spam`, `.shrug` (inspect rate/scope behavior before using).
- Secure note/vault families: `.savenote`, `.getnote`, `.delnote_sec`, `.vault [set|get|rm|list] ...`. Keep encrypted vault key/plaintext secret.
- `.logger`, `.mirror`, `.setlogger`, `.read` — forensic logging surfaces; privacy/consent/retention are critical.
- `.savevo` — ephemeral/view-once related helper; inspect behavior carefully.
- `.hash <text>`, `.passgen [length]`.
- Utilities: `.uuid`, `.sha256`, `.jsonfmt`, `.b64`, `.urlencode`, `.timestamp`, `.head`, `.rss`.
- Productivity module additionally contains reminders/filters/notes-like workflows; inspect `plugins/productivity.py` for exact syntax rather than guessing.
- `.backup ...` — consistent SQLite snapshot and copy to configured Rclone remote.
- `.cleancache` removes staging/cache files and is intended not to touch persistent databases or the Telegram session.

This is a useful category-level catalog, not a replacement for the live command registry. Some large plugins register multiple commands in code; query `.help` and `.command describe` for the exact deployed contract.

## 7. Intelligence and investigation architecture

Astra has an IntelGraph foundation for canonical entities, observations, graph relationships, provenance, confidence/evidence states, correlation and automation ingestion. IOC extraction/normalization is a related service. Public-source modules cover Telegram observable intelligence, username pivots, domains, certificate transparency, links and public-code/Git intelligence. Security intelligence includes URL/domain/hash reputation and IDN/homoglyph risk. Media intelligence includes OCR/STT-derived evidence, media hashes/similarity and case integration. Cases contain graph/evidence, events, timeline and report workflows.

Important distinction: code and design documents exist, but `docs/INTELGRAPH.md` and `docs/IOC_ENGINE.md` at inspection state say implementation is complete with local acceptance pending. The product-maturity ledger also lists owner-host target/correlation smoke as pending. Do not claim all intelligence flows are production-accepted without current evidence.

### Unified search

One SearchService front door indexes bounded domains (including commands and intelligence/case/media evidence). It uses stable result identities, source filters, query-bound cursors, bounded limits and FTS5. Do not build a second search engine. Search indexes are derived and rebuildable. See `docs/UNIFIED_SEARCH.md`.

### Unified entity inspector and correlation

`.inspect` resolves typed targets through existing identity/IntelGraph services; ambiguous targets should not be silently selected. Evidence/source references must be retained. `.correlate` surfaces relationships and evidence state; a relationship is not proof of identity. Keep confidence and uncertainty visible.

### Dataset / Hugging Face intelligence track

This is a major future track and **not complete**. Before building query adapters or ingesting large datasets, the roadmap requires:
1. account/source census;
2. complete dataset inventory;
3. family clustering;
4. duplicate detection using multiple evidence levels;
5. derived/subset/merge/composite detection;
6. root/master candidate analysis;
7. lineage graph;
8. unique-coverage measurement;
9. fork/retain decisions;
10. frozen canonical source manifest;
11. only then remote query, schema mapping, provenance, lineage-aware aggregation, cache and IntelGraph ingestion.

Do not download huge datasets, fork random sources, treat repository count as unique coverage, or count duplicate datasets as independent corroboration. DS-*, DS-ACCEPT-* and HF-* gates remain blocked until their evidence requirements are satisfied.

## 8. Security and trust boundaries

- `config.py` validates required positive integer API ID/owner ID and required API hash/text values. It supports preferred `ASTRA_*` environment names plus compatibility aliases.
- Real credentials belong in ignored local `.env`; use `.env.example` only as a template. Session is file-based under `data/`. Never commit it.
- `main.py` applies a logging filter for labeled credential-shaped values, Bearer tokens and sufficiently long high-entropy Telethon StringSession-shaped values. This is defense in depth, not permission to log secrets.
- Vault uses cryptography-backed storage; never log plaintext or master key.
- `SAFE_MODE=1` is documented as skipping plugin initialization; do not confuse it with a complete OS sandbox or authorization substitute.
- Capability declarations and grants are distinct. The platform enforces capability/effect checks at trusted service boundaries; do not assume a plugin is safe merely because metadata declares a capability.
- Plugin modules execute in the same Python process; a malicious or buggy plugin is not automatically contained by OS isolation.
- Bubblewrap isolation is used for classified child workloads where configured/available. If the reviewed backend is unavailable, stop or report degraded state rather than falsely claiming isolation.
- Network and subprocess operations must have timeout, output/body caps, redirect policy, URL/argument validation, cancellation and resource bounds.
- Telegram writes need bounded target scope, operation policy and audit; uncertain effects require reconciliation.
- Monitoring/health checks should be observational, not silently remediate.
- Treat Telegram messages, URLs, media, AI output and plugin-provided content as untrusted input.
- No arbitrary AI tool calls: model output cannot authorize Telegram mutation, broaden scopes or bypass rate/capability policy.

## 9. Configuration and local operation

The canonical configuration reference is `.env.example`; the current `config.py` directly requires:
- `ASTRA_API_ID` (or legacy `API_ID`);
- `ASTRA_API_HASH` (or `API_HASH`);
- `ASTRA_OWNER_ID` (or `OWNER_ID`).

Relevant settings documented across config/env/service code include session basename, prefix (default `.`), log level, safe mode, optional Groq/Gemini provider credentials, AI provider/fallbacks, remote AI opt-in/budget, Rclone remote, vault master key and archive retention/capacity. **Do not copy real values into this document or chat.** Read the live service config parser before assuming every example variable is consumed identically.

Current known local development environment from owner history (may have changed): Linux desktop, project checkout previously at `~/Downloads/astra_beautified_v2`; Python 3.14.7; Telethon 1.44.0; local session under `data/astra_session.session`. Do not assume this local checkout is synced to current GitHub `main`; verify commit/status before advising local edits. The repository is the current reference for this handoff.

Typical development checks documented by README:

```bash
python -m pytest -q
python -m compileall -q core plugins tools
python tools/plugin_behavior_check.py
python tools/plugin_ecosystem_check.py
python tools/media_pipeline_check.py
python tools/isolation_security_check.py
python tools/storage_hardening_check.py
python tools/job_hardening_check.py
python tools/production_hardening_check.py
python tools/shutdown_probe.py
python tools/release_acceptance.py
```

Use `python tools/docs_check.py` for docs/inventory link consistency. Follow `docs/operations/SETUP.md` and the runbook for actual setup and systemd steps. Do not run every command against live Telegram as a test. `.testall` has safe/report/network/static modes and explicitly skips mutating commands.

## 10. Tests, audits and current verification status

The repository has broad test coverage for:
- SDK facade and SDK equivalence;
- plugin contract/manager/ecosystem and setup rollback;
- command router/registry;
- capability enforcement;
- task and shutdown lifecycle;
- durable jobs, resource bounds, leases/reconciliation and send/edit/delete/join/upload recovery;
- SQLite storage hardening, migrations and secret redaction;
- AI gateway/product, provider boundaries and durable AI jobs;
- automation triggers, durability and JobEngine integration;
- Telegram state, sync, events, event journal/projections/replay, traffic and archive;
- media service/intelligence and cases;
- search, intelligence graph, public/security intelligence and IOC;
- operator/product maturity/platform controls.

At a previous documented acceptance point, the automation Program G had owner-host acceptance recorded as complete (2026-09-17) and the AI Program F recorded successful representative runtime checks. Those are historical evidence in docs; re-check commits/docs before asserting current production state.

The current post-Phase-10 acceptance ledger has many implementation-level checks marked complete, but it explicitly lists **owner-host/live acceptance still pending** for items such as:
- command discovery live smoke;
- search permission/scope smoke;
- entity inspector target smoke for URL/domain/username/Telegram/entity;
- correlation contradiction/unknown live smoke;
- interactive callback production smoke;
- plugin lifecycle live smoke and owner-host compatibility audit;
- live AI provider and media OCR/STT smoke;
- owner-host systemd, update and restart/recovery smoke.

The roadmap says Phases 1–10 have been completed through the Security + Ecosystem gate, but post-Phase-10 A–H acceptance is not automatically complete. Treat `docs/acceptance/POST_PHASE10_ACCEPTANCE.md` (if present in the current branch) and the product maturity ledger as the authority for remaining gates. Never fabricate a passing run.

## 11. Roadmap: done, active baseline, and not implemented

The roadmap is intentionally much larger than the current implementation. It uses gates and prerequisite ordering; do not start the most exciting feature if a required source, identity, evidence, job or storage contract is missing.

### Numbered implementation phases

The roadmap states that numbered Phases 1–10 have been completed through the Security + Ecosystem gate. The phase families were:

1. Telegram Core 2.0 — traffic governor, operation/priority classes, flight recorder and operator views.
2. Telegram State + Events — entity/dialog/capability caches, incremental sync, event collector/journal/projections/replay.
3. Archive + UX Foundation — durable archive, state foundations and interaction building blocks.
4. Product Feature Expansion — productivity, group management, Telegram/media/web/network utilities.
5. AI Product 2.0 — unified bounded AI, context-aware requests, AI jobs and zero-cost provider strategy.
6. Automation — declarative trigger/rule/action engine integrated with JobEngine and recovery.
7. Intelligence Foundation — IntelGraph canonical entities, observations, evidence and correlation foundation.
8. Intelligence Sources — IOC, TGINTEL, username/entity, domain/infrastructure, link and related source programs.
9. Media + Investigation — media intelligence, timelines, cases and reports.
10. Security + Ecosystem — defensive security intelligence, SDK/registry/compatibility and selected competitor feature catch-up.

This phase summary does not override any per-feature acceptance record. Historical gates can be complete while a later maturity/live gate remains pending.

### Post-Phase-10 A–H execution baseline

The roadmap's current maturity track is:
- **A — Command Contract + Discoverability:** stable metadata, help/search/describe/examples/category/aliases/permissions/source/recent.
- **B — Unified Search:** one cross-domain SearchService, bounded filters/cursors and stable result IDs.
- **C — Unified Entity Inspector:** reuse identity resolver; ambiguity and provenance preserved.
- **D — Correlation / Intelligence UX:** evidence-aware relationships and visible confidence/unknown/contradiction states.
- **E — Interactive UX Maturity:** reusable bounded buttons/forms/galleries/lists/progress/confirmations and structured errors.
- **F — Plugin UX + Compatibility:** catalog/detail/search/health/lifecycle operations and SDK compatibility.
- **G — AI Product UX:** contextual AI across replies, search, evidence, cases, timelines and media while AI remains advisory.
- **H — Astra Control Plane / Operator UX:** doctor/config/update/restart/status/health/jobs/plugins, safe first-run and recoverable operations.

These changes are described as an implementation baseline in roadmap/acceptance docs; final release acceptance still requires focused tests, full regression, compileall, plugin/media/security/search/storage audits, production acceptance, owner-host Telegram smoke, systemd restart/recovery and synchronized evidence.

### Explicitly deferred / not implemented or not yet accepted

1. **Dataset census and Hugging Face lineage/query integration:** blocked until all DS prerequisites and source manifest gates are done.
2. **Additional intelligence source adapters and expanded intelligence coverage:** only implement after source registry/provenance/lineage prerequisites and scope are clear.
3. **Expanded media intelligence:** perceptual clustering, screenshot intelligence and deeper audio/video analysis are roadmap directions; check actual service/tests before claiming completion.
4. **Remaining AI quality work:** OCR preprocessing/language/layout improvements, STT accuracy improvements, and richer multimodal context are explicitly deferred quality work. Never imply extraction is infallible.
5. **Further automation features:** current rule/trigger/action engine exists; future actions must preserve declarative typed contracts and not add arbitrary execution.
6. **Further plugin SDK/compatibility work:** SDK facade and deterministic scaffold generator exist, but future capability migration and ecosystem maturity need the roadmap's explicit gates.
7. **Interactive UX expansion:** primitives and selected job flows exist; optional migration of every read-only surface and owner-host callback smoke may remain.
8. **Live/production acceptance:** many post-Phase-10 gates are explicitly still awaiting owner-host smoke at the inspected acceptance checkpoint.
9. **Competitor parity:** selective UX/product gaps only; no command-count cloning. Do not copy a feature just because another userbot has it.
10. **Release 1.0.1 tag:** README says it is not tagged until the owner-host Telegram/systemd acceptance checklist passes. Check current release docs before tagging.

### Deliberately not building

- paid infrastructure as a requirement;
- a mandatory hosted LLM or mandatory local LLM;
- a second Telegram transport;
- a second command registry, scheduler, workflow engine, search engine, identity resolver or correlation engine;
- AI as authorization/decision authority;
- blind plugin/package installation;
- arbitrary Python/expression execution inside automation rules;
- fake process sandboxing claims;
- unbounded history scans, queues, downloads, AI context or subprocess output;
- “success” inferred from an uncertain external side effect;
- dataset forks/adapters before lineage and unique coverage are measured.

## 12. Engineering rules for future changes

### For every new command
- Register through the canonical registry and give complete metadata/examples.
- Specify permission/owner policy, operation/effect class, required capability, scope, network/destructive/confirmation flags, timeout/priority and durable-job semantics.
- Make it discoverable through `.help` and `.command`.
- Keep aliases deterministic; prevent collisions.
- Add safe tests for parsing, authorization, scope, resource limits and failure behavior.

### For every new plugin
- Use SDK metadata and the scaffold generator where appropriate.
- Declare required/optional dependencies correctly.
- Declare capabilities honestly; declaration is not enforcement.
- Use shared services and tracked tasks/jobs/resources.
- Ensure setup failure rolls back registrations and resources.
- Implement bounded shutdown for owned resources.
- Do not install packages or execute arbitrary remote code.
- Add plugin contract tests and ecosystem audit coverage.

### For every external side effect
- Establish explicit actor/owner authorization and exact target scope.
- Apply traffic/rate policy.
- Bound input/output/time/resources.
- Persist durable intent before work where needed.
- Make idempotency explicit.
- Verify completion; if outcome is unknown, preserve `UNCERTAIN` and reconcile.
- Audit without secrets.
- Test restart/cancellation/partial failure and duplicate invocation.

### For every intelligence feature
- Identify canonical entity and observation types first.
- Preserve source/provenance, timestamps, confidence/evidence state and contradictions.
- Distinguish observed facts from derived relationships and AI synthesis.
- Treat correlation as a hypothesis, not identity proof.
- Allow unknown state.
- Do not treat duplicated/derived datasets as independent corroboration.

### For every storage/schema change
- Add versioned migration and checksum/integrity behavior.
- Preserve foreign keys and historical audit/job data.
- Define retention, migration rollback/forward behavior and rebuildability of derived data.
- Test backup/restore and interrupted migration paths.
- Do not log secrets or message contents without a clear approved contract.

### For every AI change
- Use AIService/provider adapters, bounded prompts/context/output and request budgets.
- Keep remote provider opt-in and local Ollama loopback-only.
- AI output cannot execute tools, authorize effects, bypass policy or expand scope.
- Keep evidence references in prompts/synthesis where appropriate.
- Test provider timeout, invalid output, retry and budget exhaustion.

## 13. Suggested first work session for Qwen

1. Confirm branch and current commit; inspect the current tree and uncommitted state if a local checkout is available. Do not assume the owner's local checkout is current.
2. Read the canonical architecture, production boundary, data/job model, plugin ecosystem, SDK and current acceptance ledger.
3. Run the non-destructive release gate in a development environment and capture failures without leaking environment values.
4. Generate/read the live plugin registry and command catalog; distinguish active, quarantined, disabled and failed modules.
5. Compare each post-Phase-10 gate against source, tests and owner-host evidence; write a precise remaining-work matrix.
6. Check the dataset/Hugging Face census gate before touching remote intelligence datasets.
7. Propose a prioritized issue list with dependencies, risk, files likely to change and exact acceptance tests. Do not implement a sweeping rewrite before this audit.
8. For actual changes, implement one coherent gate at a time, test locally, update docs/acceptance, and report what remains unverified.

## 14. Canonical files to read first

| File | Why it matters |
|---|---|
| `README.md` | Project position, principles, verification and operations |
| `main.py`, `client.py`, `config.py` | Runtime startup, auth/config, shutdown and logging |
| `core/context.py`, `core/bootstrap.py` | Shared runtime and lifecycle |
| `core/registry.py` | Canonical command contract and dispatch metadata |
| `core/plugins/manager.py`, `core/plugins/capabilities.py` | Plugin lifecycle, capabilities and enforcement |
| `core/database.py`, `core/services/storage.py` | Durable persistence and migrations |
| `core/services/jobs.py`, `docs/architecture/JOB_MODEL.md` | Durable side effects, leases, retries and uncertainty |
| `core/services/telegram.py`, `telegram_traffic.py`, `telegram_events.py` | Telegram boundary, traffic policy and events |
| `core/services/ai.py`, `plugins/ai_gateway/unified.py` | AI provider and product path |
| `core/services/automation.py`, `plugins/automation.py` | Declarative automation and durable runs |
| `core/services/search.py`, `docs/UNIFIED_SEARCH.md` | Unified search contract |
| `core/services/intelgraph.py`, `docs/INTELGRAPH.md`, `docs/IOC_ENGINE.md` | Evidence graph and intelligence |
| `core/services/media.py`, `media_intel.py`, `docs/media/MEDIA_PIPELINE_HARDENING.md` | Media bounds, isolation, evidence |
| `astra/sdk.py`, `astra/sdk_generator.py`, `PLUGIN_SDK.md` | Supported plugin extension API |
| `docs/roadmap/ROADMAP.md` | Full A–T map, prerequisites and future work |
| `docs/acceptance/PRODUCT_MATURITY_ACCEPTANCE.md` | Gate-by-gate current acceptance status |
| `docs/operations/OPERATIONS_RUNBOOK.md` | Safe production operations |
| `docs/operations/DISASTER_RECOVERY.md` | Backup/recovery contracts |
| `tools/release_acceptance.py` | Canonical non-destructive release verification |
| `tests/` | Regression truth for contracts and failure cases |

## 15. Source links

- Repository: https://github.com/Exploiter69/astraUserbot
- README: https://github.com/Exploiter69/astraUserbot/blob/main/README.md
- Architecture: https://github.com/Exploiter69/astraUserbot/blob/main/docs/architecture/ARCHITECTURE.md
- Roadmap: https://github.com/Exploiter69/astraUserbot/blob/main/docs/roadmap/ROADMAP.md
- Product maturity acceptance: https://github.com/Exploiter69/astraUserbot/blob/main/docs/acceptance/PRODUCT_MATURITY_ACCEPTANCE.md
- Plugin ecosystem: https://github.com/Exploiter69/astraUserbot/blob/main/docs/plugins/PLUGIN_ECOSYSTEM.md
- Plugin SDK: https://github.com/Exploiter69/astraUserbot/blob/main/PLUGIN_SDK.md
- Operations runbook: https://github.com/Exploiter69/astraUserbot/blob/main/docs/operations/OPERATIONS_RUNBOOK.md

---

**Final instruction:** Astra is a reliability/safety platform with a large feature surface. Preserve its architecture, keep claims evidence-based, prioritize missing acceptance and prerequisites over new command volume, and never turn uncertainty into authority.
