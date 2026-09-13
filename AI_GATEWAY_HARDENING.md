# AI Gateway Hardening

## Boundary

Plugins use `context.get("ai")`. Provider SDKs and HTTP details stay inside `core/services/ai.py`; the shared `HttpService` owns network transport.

## Providers

- `groq`: free-tier remote provider when the user's existing key/account permits it.
- `gemini`: free-tier remote provider when the user's existing key/account permits it.
- `ollama`: local-only provider at `127.0.0.1:11434` by default.

The gateway has no OpenRouter dependency and does not select arbitrary paid providers or arbitrary remote endpoints.

## Reliability

- Per-request timeout plus `asyncio.wait_for` cancellation boundary.
- Caller cancellation propagates; it is never converted into provider fallback.
- Provider failures can fall through the configured fallback chain only for gateway-owned automatic calls.
- Explicit provider selection never falls back silently.
- Shared HTTP retries remain bounded; local Ollama requests disable network retries.
- Provider responses are schema-validated and empty/malformed responses fail closed.

## Resource limits

- Input: 100,000 characters by default.
- Message count: 64.
- Individual message: 50,000 characters.
- Output: 30,000 characters.
- Provider generation: 8,192 tokens.
- Audio: 100 MiB.
- AI concurrency: 2 requests by default.
- HTTP response: 2 MiB per AI provider response.

## Tool/function-call safety

The gateway accepts text-only `role`/`content` messages. Provider responses containing `tool_calls` or `function_call` are rejected. AI therefore cannot directly execute tools, shell commands, filesystem mutations, Telegram mutations, jobs, or other privileged operations.

AI output is data. Mutation-capable plugins remain responsible for explicit authorization, validation, execution, and verification.

## Zero-cost guardrails

Remote providers are explicitly switchable with `ASTRA_AI_REMOTE_ENABLED` and bounded by `ASTRA_AI_MAX_REMOTE_REQUESTS` over `ASTRA_AI_REMOTE_WINDOW_SECONDS`. The default fallback chain is `gemini,ollama`, but local Ollama remains the no-network fallback when remote access is disabled or exhausted.

This is a usage guardrail, not a provider billing guarantee: free-tier availability and quotas are controlled by the provider/account. Astra does not contain paid-provider routing.

## Legacy AI plugins

These remain quarantined and are not reactivated as part of this hardening:

- `plugins.ai.ask`
- `plugins.ai.groq_client`
- `plugins.ai.summarize`
- `plugins.ai.transcribe`

The active AI surface is `plugins/ai_gateway/*` plus the process-wide gateway service.

## Verification

Run:

```bash
./venv/bin/python -m pytest -q
./venv/bin/python tools/ai_gateway_hardening_audit.py
```

The AI hardening gate must pass without requiring a live provider request.
