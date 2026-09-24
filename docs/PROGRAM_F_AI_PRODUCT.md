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

**Runtime note:** image OCR and transcription are functionally working, but extraction/transcription accuracy is not treated as a Phase 5 architecture gate. Accuracy improvements are explicitly deferred to a post-Phase-5 quality pass.

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

## Phase 5 runtime evidence

The Phase 5 implementation and runtime gates were completed against the production `astra.service` path.

Observed evidence:

- focused AI/product/Telegram regression: **37 passed**
- full regression suite: **292 passed**
- production service restarted successfully after the final AI fixes
- `.aidiag`: **PASS** — provider/mode/capability/budget/limit diagnostics displayed without secrets
- `.ai`: **PASS** — normal provider-backed response
- `.explain`: **PASS** — normal provider-backed response
- `.ai --last 5`: **PASS** — bounded recent Telegram context used successfully
- `.aijob`: **PASS** — `AI_CHAT` job queued durably and later reached `COMPLETED`, progress `100%`, attempt `1/3`
- image → OCR → AI: **PASS** — reply-based image context is detected and OCR text reaches the AI request
- audio/voice → transcription: **PASS** — transcription path is functional
- existing `.ocr`: **PASS** as a standalone media utility

A Phase 5 implementation bug discovered during runtime smoke was fixed: `.aijob` passed the JobEngine UX helper's `state` argument positionally instead of by keyword. The fix was committed before final validation.

A second runtime integration issue was fixed: Telegram photo media can expose `.photo` without a MIME type, so unified AI media routing now detects photos and document MIME types rather than relying only on `media.mime_type`.

The individual `.rewrite`, `.translate`, `.extract`, and `.code` commands are covered by the focused product contract suite and share the same unified gateway path; they were not separately re-smoked manually after the representative `.ai`/`.explain` runtime checks. This is recorded rather than represented as a manual smoke that did not occur.

## Acceptance

Phase 5 is **GREEN / COMPLETE** for the architecture and product gate.

Acceptance basis:

1. focused AI product tests pass — **PASS**
2. full regression suite passes — **PASS**
3. service restarts cleanly with no AI command collisions — **PASS**
4. representative unified AI commands are runtime-smoked, with the remaining command variants covered by focused contract tests — **PASS**
5. reply-based OCR/STT paths are runtime-smoked — **PASS**
6. durable AI job queue/completion/status is runtime-smoked — **PASS**
7. existing AI compatibility surface and broader regression suite remain green — **PASS**
8. runtime evidence and known limitations are recorded here and in `PHASE_5_ACCEPTANCE.md` — **PASS**

### Deferred post-Phase-5 quality work

- improve OCR preprocessing/language selection/layout handling
- improve STT accuracy through model/provider and audio preprocessing work
- evaluate richer multimodal context only when it can remain within Astra's existing bounded/isolation architecture

These are quality enhancements, not reasons to reopen the Phase 5 architecture gate.


## Post-Phase-10 AI product UX

The existing AI gateway is now also exposed through bounded product flows:

- `aiux summarize` — replied/selected text summary;
- `aiux explain` — bounded explanation;
- `aiux search <query>` — search-evidence synthesis;
- `aiux evidence <target>` — evidence explanation;
- `aiux case <case-id>` — case report draft;
- `aiux timeline <case-id>` — timeline summary;
- `aiux media` — OCR/STT evidence to AI.

These flows reuse the existing AIService, MediaIntelService, SearchService and CaseService. They do not grant the model Telegram mutation authority.
