# IOC Engine Foundation

**Gates:** INTEL-3 / INTEL-4  
**Status:** implementation pending local acceptance

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
