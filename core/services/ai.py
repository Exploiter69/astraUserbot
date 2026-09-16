"""Provider-independent AI gateway with bounded, cancellable execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

import aiohttp

from core.errors import ConfigurationError, ExternalServiceError, ResourceError, TimeoutError
from core.services.http import HttpResponse, HttpService

logger = logging.getLogger("astra.services.ai")


@dataclass(frozen=True, slots=True)
class AIResponse:
    """Provider-neutral AI result and non-sensitive execution metadata."""
    text: str
    provider: str
    model: str
    input_chars: int
    output_chars: int


class AIProvider(Protocol):
    name: str
    supports_transcription: bool
    is_remote: bool

    async def chat(self, messages: Sequence[dict[str, str]], *, model: str, temperature: float, max_output_tokens: int, timeout: float) -> str: ...
    async def transcribe(self, file_path: str, *, model: str, timeout: float) -> str: ...


class _HTTPProvider:
    is_remote = True

    def __init__(self, name: str, http: HttpService, base_url: str, api_key: str = "") -> None:
        self.name = name
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.supports_transcription = False

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(self, messages, *, model, temperature, max_output_tokens, timeout):
        if not self.api_key:
            raise ConfigurationError(f"{self.name.upper()} credentials are not configured.")
        payload = {"model": model, "messages": list(messages), "temperature": temperature, "max_completion_tokens": max_output_tokens}
        response = await self.http.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            data=json.dumps(payload).encode("utf-8"),
            timeout=timeout,
            response_limit=2 * 1024 * 1024,
            retries=2,
        )
        return _chat_text(response, self.name)

    async def transcribe(self, file_path, *, model, timeout):
        raise ConfigurationError(f"AI provider '{self.name}' does not support transcription.")


class GroqProvider(_HTTPProvider):
    default_model = "openai/gpt-oss-20b"

    def __init__(self, http, api_key):
        super().__init__("groq", http, "https://api.groq.com/openai/v1", api_key)
        self.supports_transcription = True

    async def transcribe(self, file_path, *, model, timeout):
        if not self.api_key:
            raise ConfigurationError("GROQ credentials are not configured.")
        path = Path(file_path)
        try:
            payload = aiohttp.FormData()
            with path.open("rb") as handle:
                payload.add_field("file", handle, filename=path.name)
                payload.add_field("model", model)
                response = await self.http.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=payload,
                    timeout=timeout,
                    response_limit=2 * 1024 * 1024,
                    retries=2,
                )
        except FileNotFoundError as exc:
            raise ResourceError("The audio file no longer exists.") from exc
        data = _json_object(response, "Groq transcription")
        text = data.get("text")
        if not isinstance(text, str):
            raise ExternalServiceError("The transcription provider returned an invalid response.")
        return text.strip()


class GeminiProvider:
    name = "gemini"
    default_model = "gemini-2.5-flash"
    supports_transcription = False
    is_remote = True

    def __init__(self, http, api_key):
        self.http, self.api_key = http, api_key

    async def chat(self, messages, *, model, temperature, max_output_tokens, timeout):
        if not self.api_key:
            raise ConfigurationError("GEMINI credentials are not configured.")
        system_parts, contents = [], []
        for message in messages:
            role, text = message["role"], message["content"]
            if role == "system":
                system_parts.append(text)
                continue
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})
        payload = {"contents": contents, "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens}}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        response = await self.http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            data=json.dumps(payload).encode("utf-8"),
            timeout=timeout,
            response_limit=2 * 1024 * 1024,
            retries=2,
        )
        data = _json_object(response, "Gemini")
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalServiceError("The AI provider returned an invalid response.") from exc
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text.strip():
            raise ExternalServiceError("The AI provider returned an empty response.")
        return text.strip()

    async def transcribe(self, file_path, *, model, timeout):
        raise ConfigurationError("The configured Gemini adapter does not provide transcription.")


class OllamaProvider:
    name = "ollama"
    default_model = "qwen2.5:7b"
    supports_transcription = False
    is_remote = False

    def __init__(self, http, base_url):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ConfigurationError("Ollama must use a local HTTP loopback endpoint.")
        self.http, self.base_url = http, base_url.rstrip("/")

    async def chat(self, messages, *, model, temperature, max_output_tokens, timeout):
        payload = {"model": model, "messages": list(messages), "stream": False, "options": {"temperature": temperature, "num_predict": max_output_tokens}}
        response = await self.http.post(
            f"{self.base_url}/chat",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
            timeout=timeout,
            response_limit=2 * 1024 * 1024,
            retries=0,
        )
        data = _json_object(response, "Ollama")
        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ExternalServiceError("Ollama returned an invalid chat response.")
        text = message["content"].strip()
        if not text:
            raise ExternalServiceError("Ollama returned an empty response.")
        return text

    async def transcribe(self, file_path, *, model, timeout):
        raise ConfigurationError("Ollama does not provide transcription through the Astra gateway.")


def _json_object(response: HttpResponse, provider: str) -> dict[str, Any]:
    if response.status >= 400:
        raise ExternalServiceError(f"{provider} rejected the AI request (HTTP {response.status}).")
    try:
        data = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalServiceError(f"{provider} returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ExternalServiceError(f"{provider} returned an invalid response.")
    return data


def _chat_text(response: HttpResponse, provider: str) -> str:
    data = _json_object(response, provider)
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExternalServiceError(f"{provider} returned an invalid chat response.") from exc
    if not isinstance(message, dict):
        raise ExternalServiceError(f"{provider} returned an invalid chat response.")
    if message.get("tool_calls") or message.get("function_call"):
        raise ExternalServiceError("AI tool/function calls are disabled by the gateway.")
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
    if not isinstance(content, str) or not content.strip():
        raise ExternalServiceError(f"{provider} returned an empty response.")
    return content.strip()


class AIService:
    """Provider-independent AI boundary with explicit zero-cost guardrails."""

    DEFAULT_GROQ_MODEL = GroqProvider.default_model
    DEFAULT_GEMINI_MODEL = GeminiProvider.default_model
    DEFAULT_OLLAMA_MODEL = OllamaProvider.default_model
    DEFAULT_TRANSCRIBE_MODEL = "whisper-large-v3"
    DEFAULT_FALLBACKS = ("gemini", "ollama")

    def __init__(self, http, *, provider=None, max_input_chars=100_000, max_output_chars=30_000, max_output_tokens=8_192, concurrency=2, timeout=90.0, fallback_providers=None, max_remote_requests=None, remote_window_seconds=None, providers=None):
        if min(max_input_chars, max_output_chars, max_output_tokens, concurrency) <= 0 or timeout <= 0:
            raise ValueError("AI limits must be positive")
        self.http = http
        self.provider_name = (provider or os.getenv("ASTRA_AI_PROVIDER", "groq")).strip().lower()
        self.max_input_chars = int(max_input_chars)
        self.max_output_chars = int(max_output_chars)
        self.max_output_tokens = int(max_output_tokens)
        self.max_message_count = 64
        self.max_message_chars = 50_000
        self.concurrency = int(concurrency)
        self.timeout = float(timeout)
        self.remote_enabled = os.getenv("ASTRA_AI_REMOTE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._providers = {
            "groq": GroqProvider(http, os.getenv("GROQ_API_KEY", "")),
            "gemini": GeminiProvider(http, os.getenv("GEMINI_API_KEY", "")),
            "ollama": OllamaProvider(http, os.getenv("ASTRA_AI_OLLAMA_URL", "http://127.0.0.1:11434/api")),
        }
        if providers:
            for name, adapter in providers.items():
                clean_name = str(name).strip().lower()
                if not clean_name or len(clean_name) > 64 or not clean_name.replace("_", "").replace("-", "").isalnum():
                    raise ConfigurationError("AI provider names are invalid.")
                if not getattr(adapter, "name", "").strip():
                    raise ConfigurationError(f"AI provider '{clean_name}' has no name.")
                self._providers[clean_name] = adapter
        if fallback_providers is None:
            raw = os.getenv("ASTRA_AI_FALLBACKS", ",".join(self.DEFAULT_FALLBACKS))
            fallback_providers = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
        self.fallback_providers = tuple(dict.fromkeys(fallback_providers))
        self.max_remote_requests = int(os.getenv("ASTRA_AI_MAX_REMOTE_REQUESTS", "100")) if max_remote_requests is None else int(max_remote_requests)
        self.remote_window_seconds = float(os.getenv("ASTRA_AI_REMOTE_WINDOW_SECONDS", "86400")) if remote_window_seconds is None else float(remote_window_seconds)
        if self.max_remote_requests <= 0 or self.remote_window_seconds <= 0:
            raise ValueError("AI remote request limits must be positive")
        self._remote_requests = deque()
        if self.provider_name not in self._providers:
            raise ConfigurationError(f"Unknown AI provider '{self.provider_name}'.")
        unknown_fallbacks = set(self.fallback_providers) - set(self._providers)
        if unknown_fallbacks:
            raise ConfigurationError(f"Unknown AI fallback provider(s): {', '.join(sorted(unknown_fallbacks))}.")

    async def start(self):
        pass

    async def close(self):
        pass

    @property
    def available_providers(self):
        return tuple(self._providers)

    @property
    def capabilities(self):
        return {name: ("chat", "summarize", "extract", "classify", "transcribe") if provider.supports_transcription else ("chat", "summarize", "extract", "classify") for name, provider in self._providers.items()}

    @property
    def provider_modes(self):
        return {name: ("remote" if provider.is_remote else "local") for name, provider in self._providers.items()}

    def diagnostics(self) -> dict[str, Any]:
        now = time.monotonic()
        cutoff = now - self.remote_window_seconds
        while self._remote_requests and self._remote_requests[0] <= cutoff:
            self._remote_requests.popleft()
        used = len(self._remote_requests)
        return {
            "provider": self.provider_name,
            "providers": self.available_providers,
            "modes": self.provider_modes,
            "capabilities": self.capabilities,
            "remote_enabled": self.remote_enabled,
            "remote_requests_used": used,
            "remote_requests_limit": self.max_remote_requests,
            "remote_requests_remaining": max(0, self.max_remote_requests - used),
            "remote_window_seconds": self.remote_window_seconds,
            "max_input_chars": self.max_input_chars,
            "max_output_chars": self.max_output_chars,
            "max_output_tokens": self.max_output_tokens,
            "max_message_count": self.max_message_count,
            "max_message_chars": self.max_message_chars,
            "concurrency": self.concurrency,
            "timeout": self.timeout,
        }

    def _provider(self, name=None):
        selected = (name or self.provider_name).lower()
        try:
            return self._providers[selected]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown AI provider '{selected}'.") from exc

    def _model(self, provider, model, *, transcription=False):
        if model:
            clean = model.strip()
            if not clean or len(clean) > 128 or any(char.isspace() for char in clean):
                raise ResourceError("AI model name is invalid or too long.")
            return clean
        if transcription:
            return os.getenv("ASTRA_AI_TRANSCRIBE_MODEL", self.DEFAULT_TRANSCRIBE_MODEL)
        defaults = {"groq": self.DEFAULT_GROQ_MODEL, "gemini": self.DEFAULT_GEMINI_MODEL, "ollama": self.DEFAULT_OLLAMA_MODEL}
        env_names = {"groq": "ASTRA_AI_GROQ_MODEL", "gemini": "ASTRA_AI_GEMINI_MODEL", "ollama": "ASTRA_AI_OLLAMA_MODEL"}
        if provider in defaults:
            return os.getenv(env_names[provider], defaults[provider])
        adapter_default = getattr(self._provider(provider), "default_model", "default")
        clean = str(adapter_default).strip()
        if not clean or len(clean) > 128 or any(char.isspace() for char in clean):
            raise ResourceError("AI provider default model is invalid or too long.")
        return clean

    def _validate_messages(self, messages):
        if not messages:
            raise ResourceError("AI requests require at least one message.")
        if len(messages) > self.max_message_count:
            raise ResourceError("AI request contains too many messages.")
        total = 0
        for message in messages:
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ResourceError("AI messages must contain only role and text content.")
            role, content = message.get("role"), message.get("content")
            if role not in {"system", "user", "assistant"} or not isinstance(content, str):
                raise ResourceError("AI messages contain an invalid role or content.")
            if len(content) > self.max_message_chars:
                raise ResourceError("An AI message exceeds the configured size limit.")
            total += len(content)
        if total > self.max_input_chars:
            raise ResourceError("AI input exceeds the configured size limit.")
        return total

    def _check_remote_budget(self, provider):
        if not provider.is_remote:
            return
        if not self.remote_enabled:
            raise ConfigurationError("Remote AI providers are disabled by the zero-cost policy.")
        now = time.monotonic()
        cutoff = now - self.remote_window_seconds
        while self._remote_requests and self._remote_requests[0] <= cutoff:
            self._remote_requests.popleft()
        if len(self._remote_requests) >= self.max_remote_requests:
            raise ResourceError("AI remote request budget is exhausted for the current window.")
        self._remote_requests.append(now)

    def _candidates(self, provider):
        return (provider.lower(),) if provider else tuple(dict.fromkeys((self.provider_name, *self.fallback_providers)))

    async def _chat_once(self, provider_name, messages, *, model, temperature):
        adapter = self._provider(provider_name)
        self._check_remote_budget(adapter)
        selected_model = self._model(provider_name, model)
        try:
            async with self._semaphore:
                text = await asyncio.wait_for(adapter.chat(messages, model=selected_model, temperature=temperature, max_output_tokens=self.max_output_tokens, timeout=self.timeout), timeout=self.timeout)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            raise TimeoutError("AI request timed out.") from exc
        if len(text) > self.max_output_chars:
            text = text[: self.max_output_chars].rstrip()
        return AIResponse(text, provider_name, selected_model, sum(len(m["content"]) for m in messages), len(text))

    async def chat(self, messages, *, model=None, provider=None, temperature=0.7):
        input_chars = self._validate_messages(messages)
        if not 0.0 <= temperature <= 2.0:
            raise ResourceError("AI temperature must be between 0 and 2.")
        candidates = self._candidates(provider)
        last_error = None
        for index, provider_name in enumerate(candidates):
            try:
                response = await self._chat_once(provider_name, messages, model=model, temperature=temperature)
                return AIResponse(response.text, response.provider, response.model, input_chars, response.output_chars)
            except asyncio.CancelledError:
                raise
            except (ConfigurationError, ExternalServiceError, TimeoutError) as exc:
                last_error = exc
                if provider is not None or index == len(candidates) - 1:
                    raise
                logger.warning("AI provider failed; trying next candidate provider=%s error=%s", provider_name, type(exc).__name__)
        raise last_error

    async def summarize(self, text, *, model=None, provider=None):
        return await self.chat([{"role": "system", "content": "You are a concise assistant. Provide a brief, bulleted summary of the following text, extracting only the most critical information."}, {"role": "user", "content": text}], model=model, provider=provider)

    async def extract(self, text, instruction, *, model=None, provider=None):
        if not instruction.strip():
            raise ResourceError("Extraction instruction cannot be empty.")
        return await self.chat([{"role": "system", "content": "Extract only the requested information. Do not invent facts."}, {"role": "user", "content": f"Request: {instruction}\n\nText:\n{text}"}], model=model, provider=provider, temperature=0.0)

    async def classify(self, text, labels, *, model=None, provider=None):
        clean_labels = [label.strip() for label in labels if label.strip()]
        if not clean_labels or len(clean_labels) > 100 or any(len(label) > 256 for label in clean_labels):
            raise ResourceError("Classification requires 1-100 bounded labels.")
        return await self.chat([{"role": "system", "content": "Return exactly one label from the allowed list and nothing else."}, {"role": "user", "content": f"Allowed labels: {', '.join(clean_labels)}\n\nText:\n{text}"}], model=model, provider=provider, temperature=0.0)

    async def transcribe(self, file_path, *, model=None, provider=None):
        selected_provider = (provider or self.provider_name).lower()
        adapter = self._provider(selected_provider)
        self._check_remote_budget(adapter)
        if not adapter.supports_transcription:
            raise ConfigurationError(f"AI provider '{selected_provider}' does not support transcription.")
        path = Path(file_path)
        if not path.is_file():
            raise ResourceError("The audio file does not exist.")
        max_audio_bytes = int(os.getenv("ASTRA_AI_MAX_AUDIO_BYTES", str(100 * 1024 * 1024)))
        if max_audio_bytes <= 0 or path.stat().st_size <= 0 or path.stat().st_size > max_audio_bytes:
            raise ResourceError("Audio file exceeds the configured AI size limit.")
        selected_model = self._model(selected_provider, model, transcription=True)
        try:
            async with self._semaphore:
                text = await asyncio.wait_for(adapter.transcribe(str(path), model=selected_model, timeout=self.timeout), timeout=self.timeout)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            raise TimeoutError("AI transcription timed out.") from exc
        if len(text) > self.max_output_chars:
            text = text[: self.max_output_chars].rstrip()
        # Transcription has no textual prompt input. input_chars represents prompt/context characters only.
        return AIResponse(text, selected_provider, selected_model, 0, len(text))
