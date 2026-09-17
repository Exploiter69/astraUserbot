# Phase 8 — Intelligence Sources

**Status:** IMPLEMENTATION COMPLETE / OWNER-HOST ACCEPTANCE PENDING  
**Phase:** 8  
**Programs:** J Telegram Intelligence, K Identity/Username Intelligence, L Domain/Infrastructure Intelligence, M Link Intelligence, Q Git/Public-Code Intelligence  
**Primary constraint:** ₹0 / $0  
**Safety boundary:** public/legitimately observable sources only; no credential acquisition, private-data acquisition, intrusive scanning, restriction circumvention, or unsupported identity claims.

## Scope

Phase 8 turns the Phase 7 IntelGraph/IOC substrate into a bounded public-source collection layer. All adapters write normalized observations, provenance and relationships into the existing IntelGraph rather than creating parallel intelligence stores.

Roadmap gates:

- `TGINTEL-1` — Telegram intelligence collector
- `USER-1` — username pivot engine
- `DOMAIN-1` — domain intelligence
- `DOMAIN-2` — Certificate Transparency
- `LINK-1` — redirect/link graph
- `GIT-1` — public-code intelligence

## Prerequisites

Before Phase 8 implementation:

1. Phase 7 IntelGraph + IOC foundation is closed.
2. `IntelGraph` is the durable entity/observation/relationship authority.
3. `HttpService` is the only shared public-web transport; no per-plugin HTTP sessions.
4. Telegram collection uses the already accepted `TelegramFacade` / `TelegramTrafficController` path.
5. Source lineage and evidence states remain explicit.
6. External responses are bounded before parsing or persistence.
7. Public-source collection is observation-only; correlation never becomes identity proof.

## Common source contract

Every adapter:

- registers a stable `source_id` and source family;
- records provider/source type and URI where applicable;
- persists normalized entities only;
- records an observation before creating a relationship;
- attaches confidence and provenance to observations/relationships;
- never persists complete remote response bodies;
- bounds result counts and response sizes;
- treats external failures as unavailable observations rather than false negatives;
- remains safe to cancel;
- uses no paid service.

## TGINTEL-1 — Telegram intelligence collector

Target command:

`.tgintel @public_username`

The collector resolves only legitimately observable Telegram information through the existing governed transport. Current implementation records:

- normalized username;
- Telegram entity type and ID when exposed;
- public title/name where exposed;
- public bio/about where exposed;
- URLs extracted from public bio text;
- source URI/provenance;
- observation timestamp.

It deliberately does not claim ownership of external URLs or cross-platform identities.

## USER-1 — Username pivot engine

Target command:

`.userintel <username>`

The pivot engine probes a bounded set of public profile APIs:

- GitHub public user/repository surface;
- GitLab public user/project surface;
- Reddit public profile surface.

A positive result creates a `PUBLIC_PROFILE` observation linked from the normalized username. A provider failure, 404 or unavailable endpoint is not stored as a negative identity fact.

The adapter can be extended with more public providers later without changing the graph contract.

## DOMAIN-1 — Domain intelligence

Target command:

`.domainintel <domain>`

Current collection surface:

- DNS address resolution through bounded local resolution;
- public RDAP registration data;
- nameserver/registrar observations when exposed;
- bounded HTTPS metadata;
- TLS peer certificate subject/issuer metadata.

DNS results become `DOMAIN → RESOLVES_TO → IP` observations. Registration and TLS data remain source observations and do not become ownership assertions.

## DOMAIN-2 — Certificate Transparency

Target command:

`.ct <domain>`

The collector uses the public CT JSON surface and records only names under the requested domain, bounded by input/response/result limits. Discovered names become domain observations linked to the requested root domain. Certificate data is treated as public evidence, not proof of control.

## LINK-1 — Redirect/link graph

Target command:

`.linkintel <url>`

The link adapter follows at most five redirects using bounded HEAD/GET requests. It records:

`URL → URL → ... → final host/domain`

Redirect loops terminate deterministically. No crawler or unrestricted URL traversal is introduced.

## GIT-1 — Public-code intelligence

Target command:

`.gitintel <username>`

The adapter reads public GitHub repositories and GitLab public projects for the requested username and records repository URLs as public-code observations. It does not scrape repository contents, search secrets, clone repositories, or infer private ownership.

## Graph discipline

Phase 8 uses the existing relationship vocabulary:

- `LINKS_TO` for public profile, URL and repository pivots;
- `RESOLVES_TO` for DNS observations;
- `MENTIONS` for CT-discovered domain names.

Evidence remains `OBSERVED` unless a later correlation gate explicitly derives a relationship. No Phase 8 adapter is allowed to emit an unsupported identity claim.

## Resource bounds

- HTTP response limits are inherited from `HttpService` and tightened for individual adapters.
- Username input: 3–32 ASCII characters.
- Domain input: RFC-style bounded hostname shape, max 253 characters.
- CT records parsed: max 500 source records / 100 normalized names.
- Redirect chain: max 5 hops.
- Displayed observations: max 32 Telegram rows per command.
- Provider probes: fixed, small adapter list; no arbitrary site scanning.

## Non-goals

Phase 8 does not implement:

- private-account access;
- credentialed provider APIs;
- active network scanning;
- password/token discovery;
- repository secret hunting;
- identity attribution from username reuse alone;
- unrestricted web crawling;
- anti-ban or Telegram restriction bypasses;
- a second graph/database.

## Acceptance sequence

`TGINTEL-1 → USER-1 → DOMAIN-1 → DOMAIN-2 → LINK-1 → GIT-1 → full regression → production acceptance`

Each gate must have focused tests, failure-path coverage and owner-host acceptance before Phase 8 is marked COMPLETE.
