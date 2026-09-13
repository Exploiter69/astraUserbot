# AstraUserbot — Detailed Canonical Roadmap

**Status:** Canonical implementation sequence  
**Version:** 2.6  
**Cost target:** ₹0 / $0

> This file is the execution plan. Architectural changes belong in `DECISIONS.md`; contracts are defined in `ARCHITECTURE.md`, `DATA_MODEL.md`, `JOB_MODEL.md`, `SAFETY_CONTRACT.md`, and `PRODUCTION_BOUNDARY.md`.

## 0. Non-Negotiable Rules

```text
Do not destroy working behavior without evidence.
Do not mass-rewrite plugins before platform services exist.
Do not introduce paid infrastructure.
Do not treat asyncio tasks as durable jobs.
Do not let AI become authority.
Do not let caches become source-of-truth.
Do not hide plugin/task/job failures.
Do not bypass authorization for convenience.
Do not allow unbounded resource consumption.
Do not claim verification when only execution succeeded.
```

---

# Phases 0–13 — COMPLETE

Phases 0 through 13 remain complete under the previously recorded gates: baseline/protection, plugin and command foundation, shared services, cache, storage, durable jobs, P0 reliability, media platform, AI gateway, plugin migration, search/knowledge, observability, feature expansion, and measured performance work.

---

# Phase 14 — Selective Isolation / Security Hardening — COMPLETE

**Goal:** validate and enforce real security boundaries for untrusted child workloads without pretending same-process plugins are sandboxed.

Completed:

- explicit Bubblewrap executor;
- separate namespaces and disabled child networking;
- cleared/minimal child environment;
- workspace-only writable filesystem exposure;
- read-only system runtime view;
- CPU, memory, file-size, process-count and descriptor limits;
- bounded output and timeout/cancellation handling;
- argv-only subprocess execution;
- `.eval` moved behind the isolation boundary;
- FFmpeg/ffprobe and OCR decoder workloads moved behind the isolation boundary;
- canonical workspace path traversal protection;
- bounded ZIP/TAR extraction with link/special-file rejection;
- malformed-media containment probe;
- secret/environment exposure probe;
- permanent isolation/archive regression tests;
- `tools/isolation_security_audit.py` static + live gate;
- security contract/documentation update.

### Gate 14 — PENDING LOCAL VALIDATION

Run the full regression suite, compile validation, and `tools/isolation_security_audit.py` on the owner host. Bubblewrap is a required backend for the live gate; the application must not silently downgrade an explicitly isolated workload.

---

# Phase 15 — Platform Maturity

Potential deliverables:

- documented plugin SDK;
- compatibility/version policy;
- safe enable/disable;
- migration tooling;
- comprehensive self-test;
- benchmarks;
- disaster recovery procedures;
- feature flags;
- release checklist.

## Global Definition of Done

Astra is platform-mature when:

1. plugin lifecycle is observable;
2. command conflicts cannot hide;
3. long-lived tasks are supervised;
4. durable work survives restart;
5. shared HTTP/subprocess/media infrastructure is used;
6. cache is bounded and measurable;
7. persistence is migration-driven;
8. high-risk plugins have regression tests;
9. AI is provider-independent and optional;
10. diagnostics expose real health;
11. resource use is bounded;
12. secrets remain protected;
13. new features reuse infrastructure;
14. the core remains ₹0/$0.

## Execution Discipline

```text
RESEARCH
   ↓
AUDIT
   ↓
DECIDE
   ↓
DOCUMENT
   ↓
IMPLEMENT
   ↓
TEST
   ↓
MIGRATE
   ↓
VERIFY
   ↓
EXPAND
   ↓
MEASURE
```

> **Build the platform once. Make every later plugin cheaper, safer, and faster to build.**
