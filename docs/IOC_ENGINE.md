# IOC Engine Foundation

**Gates:** INTEL-3 / INTEL-4  
**Status:** implementation complete; local acceptance pending

The IOC layer is deterministic and local. It extracts bounded indicator candidates from text and canonicalizes them before graph ingestion.

Supported initial classes:

- URL
- EMAIL
- DOMAIN
- IP
- USERNAME
- HASH
- CVE

Normalization includes case folding, IP canonicalization, URL scheme/host normalization, username normalization, CVE normalization and explicit hash algorithm labeling by digest length.

Extraction is bounded to 64 KiB input and 256 unique indicators per call. The extractor is deliberately independent of network reputation providers; enrichment is a later adapter layer.

## IntelGraph integration

`IntelGraph.ingest_text()` uses this deterministic extractor as the Phase 7 ingestion primitive:

`bounded text → extract → normalize/deduplicate → typed IntelGraph entity → OBSERVED evidence`

Each emitted indicator receives:

- a canonical typed entity;
- the original observed representation as display/provenance data;
- source and source-family lineage;
- observation/retrieval timestamps;
- deterministic `OBSERVED` evidence state;
- bounded confidence;
- an `INTELLIGENCE_OBSERVED` event through the existing automation sink.

No network enrichment or identity inference occurs during extraction. Duplicate indicators in one bounded input are collapsed by `(type, normalized value)` before graph persistence.
