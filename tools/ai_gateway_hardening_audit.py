"""Static contract audit for the provider-independent AI gateway."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI = (ROOT / "core/services/ai.py").read_text(encoding="utf-8")
MANAGER = (ROOT / "core/plugins/manager.py").read_text(encoding="utf-8")
ENV = (ROOT / ".env.example").read_text(encoding="utf-8")


def check(label: str, value: bool) -> None:
    print(f"{label}: {'PASS' if value else 'FAIL'}")
    if not value:
        raise SystemExit(1)


check("provider_independent_service", 'class AIService:' in AI and 'AIProvider(Protocol)' in AI)
check("groq_adapter", '"groq": GroqProvider' in AI)
check("gemini_adapter", '"gemini": GeminiProvider' in AI)
check("local_ollama_adapter", '"ollama": OllamaProvider' in AI and 'is_remote = False' in AI)
check("provider_fallback", 'DEFAULT_FALLBACKS' in AI and 'def _candidates' in AI)
check("failure_isolation", 'except (ConfigurationError, ExternalServiceError, TimeoutError)' in AI)
check("cancellation_preserved", 'except asyncio.CancelledError:' in AI and 'raise' in AI)
check("bounded_timeout", 'asyncio.wait_for(' in AI)
check("response_limit", 'response_limit=2 * 1024 * 1024' in AI)
check("prompt_limits", 'max_input_chars' in AI and 'max_message_count' in AI and 'max_message_chars' in AI)
check("output_limits", 'max_output_chars' in AI and 'max_output_tokens' in AI)
check("tool_calls_disabled", 'tool_calls' in AI and 'function_call' in AI and 'disabled by the gateway' in AI)
check("remote_cost_guardrail", 'ASTRA_AI_MAX_REMOTE_REQUESTS' in AI and 'ASTRA_AI_REMOTE_ENABLED' in AI)
check("explicit_provider_no_fallback", 'if provider is not None or index == len(candidates) - 1' in AI)
check("no_openrouter_gateway", 'OPENROUTER' not in AI)
check("legacy_ai_quarantine", all(name in MANAGER for name in (
    'plugins.ai.ask',
    'plugins.ai.groq_client',
    'plugins.ai.summarize',
    'plugins.ai.transcribe',
)))
check("env_has_local_and_guardrails", 'ASTRA_AI_OLLAMA_URL' in ENV and 'ASTRA_AI_MAX_REMOTE_REQUESTS' in ENV)
print("AI_GATEWAY_HARDENING_AUDIT_PASS")
