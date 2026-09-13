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
from typing import Any, Protocol, Sequence

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

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout: float,
    ) -> str: ...

    async def transcribe(self, file_path: str, *, model: str, timeout: float) -> str: ...


class _HTTPProvider:
    """Small provider adapter; all network execution stays behind HttpService."""

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

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout: float,
    ) -> str:
        if not self.api_key:
            raise ConfigurationError(f"{self.name.upper()} credentials are not configured.")
        payload = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
            "max_completion_tokens": max_output_tokens,
        }
        response = await self.http.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            data=json.dumps(payload).encode("utf-8"),
            timeout=timeout,
            response_limit=2 * 1024 * 1024,
            retries=2,
        )
        return _chat_text(response, self.name)

    async def transcribe(self, file_path: str, *, model: str, timeout: float) -> str:
        raise ConfigurationError(f"AI provider '{self.name}' does not support transcription.")


class GroqProvider(_HTTPProvider):
    """Groq adapter. No Groq-specific knowledge leaks into plugins."""

    def __init__(self, http: HttpService, api_key: str) -> None:
        super().__init__("groq", http, "https://api.groq.com/openai/v1", api_key)
        self.supports_transcription = True

    async def transcribe(self, file_path: str, *, model: str, timeout: float) -> str:
        if not self.api_key:
            raise ConfigurationError("GROQ credentials are not configured.")
        path = Path(file_path)
        try:
            payload = aiohttp.FormData()
            with path.open("rb") as handle:
                payload.add_field("file", handle, filename=path.name)
                payload.add_field("model", model)
                response = await self.http.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
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
    """Google Gemini Developer API adapter."""

    name = "gemini"
    supports_transcription = False
    is_remote = True

    def __init__(self, http: HttpService, api_key: str) -> None:
        self.http = http
        self.api_key = api_key

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout: float,
    ) -> str:
        if not self.api_key:
            raise ConfigurationError("GEMINI credentials are not configured.")
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            text = message["content"]
            if role == "system":
                system_parts.append(text)
                continue
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens},
        }
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
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalServiceError("The AI provider returned an invalid response.") from exc
        if not text.strip():
            raise ExternalServiceError("The AI provider returned an empty response.")
        return text.strip()

    async def transcribe(self, file_path: str, *, model: str, timeout: float) -> str:
        raise ConfigurationError("The configured Gemini adapter does not provide transcription.")


class OllamaProvider:
    """Local Ollama adapter. It never creates a paid/remote dependency."""

    name = "ollama"
    supports_transcription = False
    is_remote = False

    def __init__(self, http: HttpService, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout: float,
    ) -> str:
        payload = {
            "model": model,
            "messages": list(messages),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_output_tokens},
        }
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

    async def transcribe(self, file_path: str, *, model: str, timeout: float) -> str:
        raise ConfigurationError("Ollama does not provide transcription through the Astra gateway.")


def _json_object(response: HttpResponse, provider: str) -> dict[str, Any]:
    if response.status >= 400:
        logger.warning("AI provider rejected request provider=%s status=%s", provider, response.status)
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
        choice = data["choices"][0]
        message = choice["message"]
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

    DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
    DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
    DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
    DEFAULT_TRANSCRIBE_MODEL = "whisper-large-v3"
    DEFAULT_FALLBACKS = ("gemini", "ollama")

    def __init__(
        self,
        http: HttpService,
        *,
        provider: str | None = None,
        max_input_chars: int = 100_000,
        max_output_chars: int = 30_000,
        max_output_tokens: int = 8_192,
        concurrency: int = 2,
        timeout: float = 90.0,
        fallback_providers: Sequence[str] | None = None,
        max_remote_requests: int | None = None,
        remote_window_seconds: float | None = None,
    ) -> None:
        if min(max_input_chars, max_output_chars, max_output_tokens, concurrency) <= 0 or timeout <= 0:
            raise ValueError("AI limits must be positive")
        self.http = http
        self.provider_name = (provider or os.getenv("ASTRA_AI_PROVIDER", "groq")).strip().lower()
        self.max_input_chars = int(max_input_chars)
        self.max_output_chars = int(max_output_chars)
        self.max_output_tokens = int(max_output_tokens)
        self.max_message_count = 64
        self.max_message_chars = 50_000
        self.timeout = float(timeout)
        self.remote_enabled = os.getenv("ASTRA_AI_REMOTE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self._semaphore = asyncio.Semaphore(int(concurrency))
        self._providers: dict[str, AIProvider] = {
            "groq": GroqProvider(http, os.getenv("GROQ_API_KEY", "")),
            "gemini": GeminiProvider(http, os.getenv("GEMINI_API_KEY", "")),
            "ollama": OllamaProvider(http, os.getenv("ASTRA_AI_OLLAMA_URL", "http://127.0.0.1:11434/api")),
        }
        configured_fallbacks = fallback_providers
        if configured_fallbacks is None:
            raw = os.getenv("ASTRA_AI_FALLBACKS", ",".join(self.DEFAULT_FALLBACKS))
            configured_fallbacks = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
        self.fallback_providers = tuple(dict.fromkeys(configured_fallbacks))
        self.max_remote_requests = int(os.getenv("ASTRA_AI_MAX_REMOTE_REQUESTS", "100")) if max_remote_requests is None else int(max_remote_requests)
        self.remote_window_seconds = float(os.getenv("ASTRA_AI_REMOTE_WINDOW_SECONDS", "86400")) if remote_window_seconds is None else float(remote_window_seconds)
        if self.max_remote_requests <= 0 or self.remote_window_seconds <= 0:
            raise ValueError("AI remote request limits must be positive")
        self._remote_requests: deque[float] = deque()
        if self.provider_name not in self._providers:
            raise ConfigurationError(f"Unknown AI provider '{self.provider_name}'.")
        unknown_fallbacks = set(self.fallback_providers) - set(self._providers)
        if unknown_fallbacks:
            raise ConfigurationError(f"Unknown AI fallback provider(s): {', '.join(sorted(unknown_fallbacks))}.")

    async def start(self) -> None:
        """AI owns no independent transport; HttpService owns the session."""

    async def close(self) -> None:
        """No provider resources are owned outside HttpService."""

    @property
    def available_providers(self) -> tuple[str, ...]:
        return tuple(self._providers)

    @property
    def capabilities(self) -> dict[str, tuple[str, ...]]:
        return {
            name: ("chat", "summarize", "extract", "classify", "transcribe")
            if provider.supports_transcription
            else ("chat", "summarize", "extract", "classify")
            for name, provider in self._providers.items()
        }

    @property
    def provider_modes(self) -> dict[str, str]:
        return {name: ("remote" if provider.is_remote else "local") for name, provider in self._providers.items()}

    def _provider(self, name: str | None = None) -> AIProvider:
        selected = (name or self.provider_name).lower()
        try:
            return self._providers[selected]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown AI provider '{selected}'.") from exc

    def _model(self, provider: str, model: str | None, *, transcription: bool = False) -> str:
        if model:
            clean = model.strip()
            if not clean or len(clean) > 128 or any(char.isspace() for char in clean):
                raise ResourceError("AI model name is invalid or too long.")
            return clean
        if transcription:
            return os.getenv("ASTRA_AI_TRANSCRIBE_MODEL", self.DEFAULT_TRANSCRIBE_MODEL)
        defaults = {"groq": self.DEFAULT_GROQ_MODEL, "gemini": self.DEFAULT_GEMINI_MODEL, "ollama": self.DEFAULT_OLLAMA_MODEL}
        env_names = {"groq": "ASTRA_AI_GROQ_MODEL", "gemini": "ASTRA_AI_GEMINI_MODEL", "ollama": "ASTRA_AI_OLLAMA_MODEL"}
        return os.getenv(env_names[provider], defaults[provider])

    def _validate_messages(self, messages: Sequence[dict[str, str]]) -> int:
        if not messages:
            raise ResourceError("AI requests require at least one message.")
        if len(messages) > self.max_message_count:
            raise ResourceError("AI request contains too many messages.")
        total = 0
        allowed_roles = {"system", "user", "assistant"}
        for message in messages:
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ResourceError("AI messages must contain only role and text content.")
            role = message.get("role")
            content = message.get("content")
            if role not in allowed_roles or not isinstance(content, str):
                raise ResourceError("AI messages contain an invalid role or content.")
            if len(content) > self.max_message_chars:
                raise ResourceError("An AI message exceeds the configured size limit.")
            total += len(content)
        if total > self.max_input_chars:
            raise ResourceError("AI input exceeds the configured size limit.")
        return total

    def _check_remote_budget(self, provider: AIProvider) -> None:
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

    def _candidates(self, provider: str | None) -> tuple[str, ...]:
        if provider:
            return (provider.lower(),)
        return tuple(dict.fromkeys((self.provider_name, *self.fallback_providers)))

    async def _chat_once(self, provider_name: str, messages: Sequence[dict[str, str]], *, model: str | None, temperature: float) -> AIResponse:
        adapter = self._provider(provider_name)
        self._check_remote_budget(adapter)
        selected_model = self._model(provider_name, model)
        try:
            async with self._semaphore:
                text = await asyncio.wait_for(
                    adapter.chat(
                        messages,
                        model=selected_model,
                        temperature=temperature,
                        max_output_tokens=self.max_output_tokens,
                        timeout=self.timeout,
                    ),
                    timeout=self.timeout,
                )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as exc:
            raise TimeoutError("AI request timed out.") from exc
        if len(text) > self.max_output_chars:
            text = text[: self.max_output_chars].rstrip()
        return AIResponse(text, provider_name, selected_model, sum(len(m["content"]) for m in messages), len(text))

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        model: str | None = None,
        provider: str | None = None,
        temperature: float = 0.7,
    ) -> AIResponse:
        input_chars = self._validate_messages(messages)
        if not 0.0 <= temperature <= 2.0:
            raise ResourceError("AI temperature must be between 0 and 2.")
        last_error: Exception | None = None
        candidates = self._candidates(provider)
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
        assert last_error is not None
        raise last_error

    async def summarize(self, text: str, *, model: str | None = None, provider: str | None = None) -> AIResponse:
        return await self.chat(
            [
                {"role": "system", "content": "You are a concise assistant. Provide a brief, bulleted summary of the following text, extracting only the most critical information."},
                {"role": "user", "content": text},
            ],
            model=model,
            provider=provider,
        )

    async def extract(self, text: str, instruction: str, *, model: str | None = None, provider: str | None = None) -> AIResponse:
        if not instruction.strip():
            raise ResourceError("Extraction instruction cannot be empty.")
        return await self.chat(
            [
                {"role": "system", "content": "Extract only the requested information. Do not invent facts."},
                {"role": "user", "content": f"Request: {instruction}\n\nText:\n{text}"},
            ],
            model=model,
            provider=provider,
            temperature=0.0,
        )

    async def classify(self, text: str, labels: Sequence[str], *, model: str | None = None, provider: str | None = None) -> AIResponse:
        clean_labels = [label.strip() for label in labels if label.strip()]
        if not clean_labels or len(clean_labels) > 100 or any(len(label) > 256 for label in clean_labels):
            raise ResourceError("Classification requires 1-100 bounded labels.")
        return await self.chat(
            [
                {"role": "system", "content": "Return exactly one label from the allowed list and nothing else."},
                {"role": "user", "content": f"Allowed labels: {', '.join(clean_labels)}\n\nText:\n{text}"},
            ],
            model=model,
            provider=provider,
            temperature=0.0,
        )

    async def transcribe(self, file_path: str, *, model: str | None = None, provider: str | None = None) -> AIResponse:
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
        return AIResponse(text, selected_provider, selected_model, 0, len(text))
