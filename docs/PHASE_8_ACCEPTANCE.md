# Phase 8 Acceptance — Intelligence Sources

**Status:** IMPLEMENTATION COMPLETE / OWNER-HOST ACCEPTANCE PENDING  
**Phase:** 8 — Intelligence Sources  
**Closed:** not yet  
**Roadmap gates:** `TGINTEL-1`, `USER-1`, `DOMAIN-1`, `DOMAIN-2`, `LINK-1`, `GIT-1`

## 1. Prerequisite gate

- [x] Phase 7 IntelGraph/IOC foundation is closed.
- [x] Existing Telegram transport/state/event/archive foundations remain the dependency boundary.
- [x] Shared `HttpService` is used for public HTTP collection.
- [x] Existing IntelGraph remains the sole durable intelligence graph.
- [x] Public-source safety boundaries are documented.
- [x] Owner-host focused tests pass: 21 passed in 1.25s.
- [ ] Owner-host full regression passes.
- [ ] Owner-host production acceptance passes.

## 2. TGINTEL-1 — Telegram intelligence collector

- [x] `.tgintel <public username>` command exists.
- [x] Uses `TelegramFacade` for Telegram resolution.
- [x] Records normalized username observation.
- [x] Records legitimately observable Telegram entity metadata.
- [x] Extracts bounded public URLs from public bio/about text.
- [x] Writes provenance/evidence to IntelGraph.
- [x] Does not infer external identity ownership.
- [x] Focused tests pass on owner host.
- [ ] Live Telegram smoke passes with a deliberately public/safe target.

## 3. USER-1 — username pivot engine

- [x] `.userintel <username>` command exists.
- [x] Input normalization and bounds are enforced.
- [x] GitHub public profile/repository surface is supported.
- [x] GitLab public profile/project surface is supported.
- [x] Reddit public profile surface is supported.
- [x] Provider failures are represented as unavailable, not false negatives.
- [x] Positive provider observations carry provider provenance and confidence.
- [x] No username reuse is presented as identity proof.
- [x] Focused tests pass on owner host.

## 4. DOMAIN-1 — domain intelligence

- [x] `.domainintel <domain>` command exists.
- [x] Bounded DNS resolution is supported.
- [x] Public RDAP lookup is supported.
- [x] Nameserver/registrar data is retained only when publicly exposed.
- [x] Bounded HTTP metadata is collected.
- [x] TLS subject/issuer metadata is collected where available.
- [x] DNS relationships are represented as observed `RESOLVES_TO` edges.
- [x] Failures do not become false observations.
- [x] Focused tests pass on owner host.

## 5. DOMAIN-2 — Certificate Transparency

- [x] `.ct <domain>` command exists.
- [x] Public CT JSON source is supported.
- [x] Result parsing is bounded.
- [x] Only names under the requested domain are retained.
- [x] CT-derived names are represented as observations.
- [x] No certificate observation is treated as proof of domain ownership.
- [x] Focused tests pass on owner host.

## 6. LINK-1 — redirect/link graph

- [x] `.linkintel <url>` command exists.
- [x] Only HTTP(S) URLs are accepted.
- [x] Redirects are followed through the shared HTTP service.
- [x] Maximum redirect depth is five.
- [x] Redirect loops terminate deterministically.
- [x] URL/domain graph edges carry source observations.
- [x] Redirect edges preserve the actual hop chain.
- [x] No unrestricted crawling is introduced.
- [x] Focused tests pass on owner host before the latest hop-chain correction; rerun is required after that correction.

## 7. GIT-1 — public-code intelligence

- [x] `.gitintel <username>` command exists.
- [x] Public GitHub repositories are supported.
- [x] Public GitLab projects are supported.
- [x] Repository observations retain public URLs and provider provenance.
- [x] No repository cloning or secret extraction is performed.
- [x] Public-code results are evidence-backed graph observations.
- [x] Focused tests pass on owner host.

## 8. Common gate requirements

- [x] No paid API/service is required.
- [x] No mandatory hosted database/service is introduced.
- [x] No second intelligence database is introduced.
- [x] External responses are bounded before parsing/persistence.
- [x] Cancellation follows existing asyncio service boundaries.
- [x] Sensitive remote response bodies are not persisted.
- [x] Existing IntelGraph evidence/confidence semantics are preserved.
- [x] Existing Telegram authorization and transport boundaries are preserved.
- [ ] Ruff format/check passes.
- [x] Focused Phase 8 tests passed: 21 passed in 1.25s before the latest link-chain correction.
- [ ] Focused Phase 8 tests rerun after latest implementation correction.
- [ ] Full test suite passes with no regression.
- [ ] `compileall` passes.
- [ ] Production acceptance gate passes.
- [ ] System-level Astra restart remains healthy.
- [ ] Live command smoke passes.

## 9. Required owner-host validation

Run after pulling the latest Phase 8 implementation:

```bash
cd ~/AstraUserbot && \
git pull --ff-only origin main && \
.venv/bin/python -m pytest -q tests/test_public_intel.py tests/test_intelgraph.py tests/test_intelgraph_phase7.py tests/test_ioc.py && \
.venv/bin/python -m compileall -q . && \
.venv/bin/python tools/production_acceptance_gate.py
```

The focused suite has already passed once on the owner host. Because the redirect graph implementation was subsequently corrected to preserve hop-to-hop edges, rerun the focused suite before relying on that earlier result. Then continue with the full regression and production acceptance gates.

## 10. Completion rule

Phase 8 must remain **PENDING** until the focused suite, full regression, production acceptance and owner-host live smoke are green. Implementation existence alone is not acceptance evidence.
