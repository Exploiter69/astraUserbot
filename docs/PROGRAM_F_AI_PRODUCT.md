# Program F — AI Product 2.0

Phase 5 turns the existing provider-independent AI gateway into a bounded Telegram product surface while keeping AI advisory, retryable, and subordinate to Astra's durable control plane.

## AI-1 — Unified AI command surface

Active commands:

- `.ai <prompt>` — generic AI request
- `.ai --last N <prompt>` — generic request with bounded recent-chat context
- `.explain <text>` — explanation
- `.rewrite <text>` — rewrite while preserving meaning
- `.translate <text>` — translation request
- `.extract <instruction>` — extraction from a supplied/replied text
- `.code <prompt>` — bounded coding assistance
- `.ask` — existing compatibility alias
- `.summarize` — existing compatibility command
- `.transcribe` — existing compatibility command
- `.aijob <prompt>` — durable AI request
- `.aidiag` — non-sensitive AI diagnostics

Existing commands remain intact; the new unified surface does not duplicate their registrations.

## AI-2 — Bounded Telegram context

`.ai --last N` retrieves at most 32 messages through `TelegramFacade`, reverses them into chronological order, and caps combined context at 24,000 characters. Individual AI messages remain subject to the core gateway limits.

Reply-based text is also supported. No unbounded history traversal is performed.

## AI-3 — Media/OCR/STT integration

A generic `.ai` request replying to an image performs bounded isolated Tesseract OCR when available and sends the extracted text to the AI gateway. Audio/voice replies are downloaded through `MediaService`, transcribed through `AIService`, and then passed to the AI request.

Temporary media workspaces are always cleaned up. Media limits remain enforced by the existing MediaService and AIService boundaries.

## AI-4 — Durable AI jobs

`.aijob` creates an `AI_CHAT` JobEngine job. The prompt is persisted in the durable job payload, execution reports bounded progress, provider/model metadata is stored in the bounded result, and transient provider/timeout failures are retryable through JobEngine semantics.

The LLM call is never the durable authority: JobEngine owns state, leasing, retry, cancellation, and recovery.

## AI-5 — Diagnostics and zero-cost guardrails

`AIService.diagnostics` exposes only operational metadata:

- configured provider
- provider modes/capabilities
- remote enabled state
- remote request usage/remaining budget/window
- input/output/message limits
- concurrency and timeout

API keys and credentials are never exposed by diagnostics.

The gateway remains provider-independent and supports the existing Groq/Gemini/Ollama adapters. No paid service or mandatory local model is introduced.

## Security and resource contract

- owner-facing commands use existing command authorization policy where required
- AI output is bounded by the core gateway
- provider function/tool calls remain disabled
- remote calls consume the configured rolling budget
- Ollama remains loopback-only
- media execution remains behind MediaService isolation
- Telegram history access remains behind TelegramFacade
- durable work remains behind JobEngine
- old quarantined AI plugins are not resurrected

## Acceptance

Phase 5 is complete only after:

1. focused AI product tests pass
2. full regression suite passes
3. service restarts cleanly with no AI command collisions
4. `.ai`, `.explain`, `.rewrite`, `.translate`, `.extract`, `.code`, `.aidiag`, and `.aijob` are smoke-tested
5. reply-based OCR/STT paths are smoke-tested where host capabilities are available
6. durable AI job completion/retry/status is smoke-tested
7. existing `.ask`, `.summarize`, `.transcribe`, archive, and durable UX regressions remain green
8. the acceptance record is updated with the observed runtime results
