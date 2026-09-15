# Phase 5 Acceptance — AI Product 2.0

## Status

**IMPLEMENTATION COMPLETE — RUNTIME ACCEPTANCE PENDING**

## Implemented

- AI-1 unified AI command surface
- AI-2 bounded Telegram context through TelegramFacade
- AI-3 image OCR and audio/voice STT integration through existing media/AI services
- AI-4 durable `AI_CHAT` JobEngine execution with progress and retry classification
- AI-5 provider/capability/remote-budget diagnostics without secrets
- focused contract tests
- product documentation

## Explicit non-goals

- no paid API or hosting requirement
- no mandatory Ollama dependency
- no legacy quarantined AI plugin restoration
- no raw Telegram history bypass around TelegramFacade
- no AI authority over durable state

## Runtime acceptance checklist

- [ ] pull latest `main`
- [ ] focused AI tests pass
- [ ] full regression suite passes
- [ ] restart `astra.service` cleanly
- [ ] `.ai` smoke
- [ ] `.ai --last N` smoke
- [ ] `.explain` smoke
- [ ] `.rewrite` smoke
- [ ] `.translate` smoke
- [ ] `.extract` smoke
- [ ] `.code` smoke
- [ ] `.aidiag` smoke
- [ ] `.aijob` → `.job` completion smoke
- [ ] durable retry smoke after a controlled failure, if safely reproducible
- [ ] image → OCR → AI smoke when Tesseract is available
- [ ] audio/voice → STT → AI smoke when supported by configured provider
- [ ] existing `.ask`, `.summarize`, `.transcribe` regression smoke
- [ ] archive and durable Telegram UX regression smoke
- [ ] journal shows no AI command collisions/import failures

Runtime evidence must be recorded here before marking Phase 5 GREEN.
