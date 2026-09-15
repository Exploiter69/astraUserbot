# Telegram UX 2.0

Astra's UX layer is deliberately thin: Telegram interaction is presentation/control, while durable state remains owned by the platform core and JobEngine.

## UX-1 — interaction primitives

Shared primitives live in `helpers/ux.py`:

- canonical durable-job cards;
- bounded text progress bars;
- state-aware inline controls;
- explicit confirmation controls;
- bounded pagination controls;
- stable short job references in operator-facing messages.

The normal text-command contract remains available. Inline UI is an enhancement, never the source of truth.

## UX-2 — pagination / progress / cancel

`plugins/system/jobs.py` provides owner-only controls:

- `.job <id>` — inspect one job;
- `.jobs [page]` — bounded job listing with Prev/Next controls;
- `.cancel <id>` — request cancellation, with confirmation for active work;
- `.retry <id>` — start a fresh durable run from a failed/cancelled job.

Inline controls expose status, cancel confirmation and retry. Callback payloads contain only a bounded job identifier; no job payload or sensitive data is placed in callback data.

Progress is read from the durable `jobs.progress` value, so UI state is reconstructible after a process restart. Active cancellation delegates to JobEngine, preserving its `UNCERTAIN` semantics when work may already have been in flight.

Manual retry creates a new JobEngine run with the original type/payload and the previous job as `parent_id`. It intentionally does not reuse the previous idempotency key, because a manual retry is an explicit new run.

## UX-3 — help / discovery / errors

The existing registry-backed `.help` remains canonical: command names and metadata are derived from live registrations, preventing a second stale command database. The new job commands therefore appear automatically in `.help` and `.help job`, `.help jobs`, `.help cancel`, and `.help retry`.

Command failures continue through the central registry error boundary and `CommandError`/`AstraError` classification. Unexpected failures receive a correlation reference rather than leaking exception details to Telegram.

## Authorization and safety

- Job-control commands are owner registrations.
- Callback actions additionally verify `config.OWNER_ID`.
- Active cancellation requires an explicit confirmation step.
- `UNCERTAIN` jobs are not automatically retried by the UX layer because an external side effect may have happened.
- UI operations do not mutate Telegram directly; they call the existing JobEngine/service boundary.
- No new paid service, hosted dependency or distributed component is introduced.

## Acceptance checklist

- [x] Text command compatibility retained.
- [x] Inline status controls.
- [x] Bounded pagination.
- [x] Durable progress rendering.
- [x] Explicit active-job cancellation confirmation.
- [x] Manual fresh-run retry for failed/cancelled jobs.
- [x] Owner-only callback authorization.
- [x] Central structured command errors retained.
- [x] UX primitive tests added.
- [ ] Production Telegram callback/pagination/cancel smoke test.
