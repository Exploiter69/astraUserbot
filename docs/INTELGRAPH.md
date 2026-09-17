# IntelGraph Foundation

**Gates:** INTEL-1 / INTEL-2 / H1 / H2 / H3  
**Status:** implementation complete; local acceptance pending

IntelGraph is Astra's local evidence substrate. It is not an identity engine and it does not treat correlations as facts.

## Canonical durable model

- `intel_sources` — source/provider/dataset identity, URI and lineage metadata.
- `intel_entities` — canonical typed entities with deterministic identity for repeated values.
- `intel_observations` — time/provenance-bearing evidence tied to a source and entity.
- `intel_relationships` — explicit graph edges with evidence state, confidence and optional supporting observation.

Every relationship is traceable to an observation when direct evidence exists, and all observations retain source and time information. Source lineage is retained so duplicate copies of one source family can later be collapsed instead of being counted as independent corroboration.

## Evidence contract

Allowed states are:

`OBSERVED`, `DERIVED`, `CORRELATED`, `INFERRED`, `UNKNOWN`, `CONTRADICTED`

Confidence is normalized to `[0, 1]`. Relationship types are explicit and bounded to the roadmap foundation vocabulary:

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

Self-relationships are rejected. Unknown relationship types and invalid evidence states are rejected. Source-family mismatches are rejected so provenance cannot silently drift.

## Graph query surface

The operator surface is:

- `.intel graph <target>`
- `.intel graph <target> <page>`

Queries resolve an exact entity/value without guessing identity. Ambiguous targets are returned as candidates rather than silently selecting one. Graph traversal is one-hop, bounded and paginated; each edge includes relationship type, evidence state, confidence and supporting observation ID where available.

The service caps graph queries at 100 edges per page and the Telegram renderer uses a smaller display page. This prevents an unbounded graph from becoming an unbounded Telegram response.

## Observation → graph ingestion

`IntelGraph.ingest_text()` connects the deterministic IOC foundation to the graph:

`bounded text → IOC extraction → normalization/deduplication → typed entity → OBSERVED evidence`

The existing IOC extractor supports URL, EMAIL, DOMAIN, IP, USERNAME, HASH and CVE. Input is bounded to 64 KiB and extraction to 256 unique indicators. Network enrichment is not performed by this gate.

## Timeline primitives

`IntelGraph.timeline(entity_id)` provides a bounded chronological evidence view by merging durable observations and relationships. The operator surface exposes it as:

- `.intel timeline <target>`
- `.intel timeline <target> <page>`

Timeline output is derived from durable graph records and does not create a second event/job system.

## Correlation boundary

`core.services.intel_correlation.IntelCorrelationEngine` is deliberately separate from storage. It classifies existing evidence and never creates an identity claim. The classification vocabulary remains:

- observed fact;
- derived relationship;
- correlated signal;
- inferred signal;
- contradiction;
- unknown.

Contradictory evidence takes precedence over a weaker correlated signal. An `UNKNOWN` relationship remains unknown when there is insufficient evidence. Confidence is bounded and the assessment includes reasons and contradiction counts for diagnostics.

## Automation integration

`IntelGraph.add_observation()` continues to emit a bounded `INTELLIGENCE_OBSERVED` event through the existing observation sink. Automation availability cannot make an already-persisted intelligence observation disappear.

## Boundary

This phase provides the trustworthy local intelligence substrate. It does not implement external dataset ingestion, broad scraping, reputation enrichment, private-data acquisition, active network scanning, or automatic identity claims. Those belong to later source/intelligence gates and must preserve this provenance/evidence contract.
