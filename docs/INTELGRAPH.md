# IntelGraph Foundation

**Gates:** INTEL-1 / INTEL-2  
**Status:** implementation pending local acceptance

IntelGraph is Astra's local evidence substrate. It is not an identity engine and it does not treat correlations as facts.

## Canonical durable tables

- `intel_sources` — source/provider/dataset identity and lineage metadata.
- `intel_entities` — canonical typed entities with deterministic identity for repeated values.
- `intel_observations` — time/provenance-bearing evidence tied to a source and entity.
- `intel_relationships` — explicit graph edges with evidence state, confidence and optional supporting observation.

## Evidence states

`OBSERVED`, `DERIVED`, `CORRELATED`, `INFERRED`, `UNKNOWN`, and `CONTRADICTED` are preserved explicitly.

Confidence is normalized to `[0, 1]`. Queries are bounded. Source lineage is retained so multiple copies of one source family can later be collapsed rather than treated as independent corroboration.

## Boundary

This gate provides the graph/storage substrate. It does not yet implement external dataset ingestion, identity claims, broad scraping, or automated correlation. Those remain downstream gates after source discovery, normalization and provenance contracts are satisfied.
