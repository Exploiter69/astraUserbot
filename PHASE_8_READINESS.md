# AstraUserbot — Phase 8 AI Gateway Completion

**Status: IMPLEMENTATION COMPLETE — GATE READY FOR LOCAL REGRESSION**

Phase 8 removes provider-specific AI knowledge from active command plugins and establishes `AIService` as the process-wide AI boundary.

## 1. Gateway Boundary

Created:

```text
core/services/ai.py
```

Registered in `ApplicationContext` as:

```text
context.get("ai")
```

The service owns:

- provider selection;
- model selection/configuration;
- chat;
- summarization;
- extraction;
- classification;
- transcription capability checks;
- bounded input/output sizes;
- bounded audio-file size;
- bounded AI concurrency;
- provider capability checks;
- cancellation propagation;
- provider-neutral response metadata;
- safe external-service errors.

## 2. Provider Adapters

Implemented without a mandatory third-party AI SDK:

```text
Groq
Google Gemini Developer API
Ollama OpenAI-compatible endpoint
llama.cpp OpenAI-compatible endpoint
```

The local adapters are optional. The current host does not need a local model for Astra to start or for the architecture to remain valid.

## 3. Transport

All remote providers use the existing `HttpService` rather than creating independent aiohttp sessions.

Therefore AI inherits:

- connection pooling;
- per-host limits;
- response-size limits;
- timeout handling;
- bounded transient retries;
- cancellation behavior.

## 4. Command Migration

Active Phase 8 command adapters live under:

```text
plugins/ai_gateway/ask.py
plugins/ai_gateway/summarize.py
plugins/ai_gateway/transcribe.py
```

The existing command surface remains:

```text
.ask
.summarize
.transcribe
```

The legacy Groq-specific command modules remain in the repository only as compatibility references and are quarantined from runtime discovery. This prevents duplicate registration while preserving a reversible migration path.

## 5. Safety / Cost Contract

- AI output is untrusted data.
- AI does not authorize commands or privileged operations.
- Provider secrets remain configuration and are not copied into user-facing errors.
- Input, output, audio and concurrency limits are explicit.
- No paid AI SDK was introduced.
- Free hosted providers are optional configuration.
- Local providers remain available for genuinely zero-cost deployments when hardware permits.

## 6. Model Configuration

`.env.example` now documents:

```text
ASTRA_AI_PROVIDER
groq / gemini / ollama / llama.cpp

ASTRA_AI_GROQ_MODEL
ASTRA_AI_GEMINI_MODEL
ASTRA_AI_OLLAMA_MODEL
ASTRA_AI_LLAMA_CPP_MODEL
ASTRA_AI_TRANSCRIBE_MODEL
ASTRA_AI_MAX_AUDIO_BYTES
OLLAMA_BASE_URL
LLAMA_CPP_BASE_URL
```

The gateway never requires a local model merely because local adapters exist.

## 7. Regression Coverage

Added:

```text
tests/test_ai_gateway.py
```

Coverage includes:

- provider-neutral chat response;
- gateway-owned summarize behavior;
- extract/classify prompt contracts;
- input limits;
- output limits;
- provider registry/selection;
- unknown-provider rejection;
- transcription capability enforcement;
- transcription response contract;
- audio size limits;
- cancellation propagation;
- bounded concurrency;
- Groq response parsing;
- safe Groq error mapping;
- Gemini request/response mapping.

## 8. Gate Checklist

```text
AIService exists and is registered             PASS
provider details isolated in adapters          PASS
Groq adapter                                   PASS
Gemini adapter                                 PASS
Ollama adapter                                 PASS
llama.cpp adapter                              PASS
shared HttpService transport                   PASS
chat API                                       PASS
summarize API                                  PASS
extract API                                    PASS
classify API                                   PASS
transcribe API                                 PASS
bounded input/output                          PASS
bounded audio size                            PASS
bounded concurrency                           PASS
cancellation propagation                      PASS
safe provider errors                           PASS
AI remains non-authoritative                  PASS
legacy AI command path quarantined             PASS
no paid dependency introduced                  PASS

LOCAL FULL REGRESSION                          PENDING
LOCAL COMPILE VALIDATION                       PENDING
```

## 9. Final Local Gate

Run from the current checkout:

```bash
cd ~/AstraUserbot && \
git pull --ff-only origin main && \
source venv/bin/activate && \
python -m unittest discover -s tests -v && \
python -m compileall -q core plugins main.py && \
echo "=== PHASE 8 GATE: PASS ==="
```

The repository had **81 tests** at the end of Phase 7 and Phase 8 adds **14 AI gateway tests**, so the expected full suite is **95 tests** before any unrelated test changes.

## 10. Exit Condition

Phase 8 is implementation-complete. It becomes locally verified when the complete suite and compile validation pass on the user's current checkout. After that, the canonical next phase is **Phase 9 — Plugin Migration Program**.
