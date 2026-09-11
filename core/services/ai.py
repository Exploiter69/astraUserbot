"""Provider-independent AI gateway with bounded, cancellable execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
        if not self.api_key and self.name == "groq":
            raise ConfigurationError("GROQ_API_KEY is not configured.")
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
            raise ConfigurationError("GROQ_API_KEY is not configured.")
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


class OllamaProvider(_HTTPProvider):
    """Optional local OpenAI-compatible Ollama adapter; never required at startup."""

    def __init__(self, http: HttpService, base_url: str) -> None:
        super().__init__("ollama", http, base_url)


class LlamaCppProvider(_HTTPProvider):
    """Optional local llama.cpp OpenAI-compatible server adapter."""

    def __init__(self, http: HttpService, base_url: str) -> None:
        super().__init__("llama.cpp", http, base_url)


class GeminiProvider:
    """Google Gemini Developer API adapter kept separate from OpenAI-compatible APIs."""

    name = "gemini"
    supports_transcription = False

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
            raise ConfigurationError("GEMINI_API_KEY is not configured.")
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role", "user")
            text = message.get("content", "")
            if role == "system":
                system_parts.append(text)
                continue
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        response = await self.http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}",
            headers={"Content-Type": "application/json"},
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


def _json_object(response: HttpResponse, provider: str) -> dict[str, Any]:
    try:
        data = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalServiceError(f"{provider} returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ExternalServiceError(f"{provider} returned an invalid response.")
    if response.status >= 400:
        detail = data.get("error")
        # Keep provider response bodies out of user-facing errors; logs may contain only status.
        logger.warning("AI provider rejected request provider=%s status=%s", provider, response.status)
        raise ExternalServiceError(f"{provider} rejected the AI request (HTTP {response.status}).")
    return data


def _chat_text(response: HttpResponse, provider: str) -> str:
    data = _json_object(response, provider)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExternalServiceError(f"{provider} returned an invalid chat response.") from exc
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
    if not isinstance(content, str) or not content.strip():
        raise ExternalServiceError(f"{provider} returned an empty response.")
    return content.strip()


class AIService:
    """Process-wide provider-independent AI boundary."""

    DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
    DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
    DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
    DEFAULT_LLAMA_CPP_MODEL = "local-model"
    DEFAULT_TRANSCRIBE_MODEL = "whisper-large-v3"

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
    ) -> None:
        if min(max_input_chars, max_output_chars, max_output_tokens, concurrency) <= 0 or timeout <= 0:
            raise ValueError("AI limits must be positive")
        self.http = http
        self.provider_name = (provider or os.getenv("ASTRA_AI_PROVIDER", "groq")).strip().lower()
        self.max_input_chars = int(max_input_chars)
        self.max_output_chars = int(max_output_chars)
        self.max_output_tokens = int(max_output_tokens)
        self.timeout = float(timeout)
        self._semaphore = asyncio.Semaphore(int(concurrency))
        self._providers: dict[str, AIProvider] = {
            "groq": GroqProvider(http, os.getenv("GROQ_API_KEY", "")),
            "gemini": GeminiProvider(http, os.getenv("GEMINI_API_KEY", "")),
            "ollama": OllamaProvider(http, os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")),
            "llama.cpp": LlamaCppProvider(http, os.getenv("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080/v1")),
        }
        if self.provider_name not in self._providers:
            raise ConfigurationError(f"Unknown AI provider '{self.provider_name}'.")

    async def start(self) -> None:
        """AI has no independent network session; HttpService owns transport lifecycle."""

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

    def _provider(self, name: str | None = None) -> AIProvider:
        selected = (name or self.provider_name).lower()
        try:
            return self._providers[selected]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown AI provider '{selected}'.") from exc

    def _model(self, provider: str, model: str | None, *, transcription: bool = False) -> str:
        if model:
            return model
        if transcription:
            return os.getenv("ASTRA_AI_TRANSCRIBE_MODEL", self.DEFAULT_TRANSCRIBE_MODEL)
        env_name = {
            "groq": "ASTRA_AI_GROQ_MODEL",
            "gemini": "ASTRA_AI_GEMINI_MODEL",
            "ollama": "ASTRA_AI_OLLAMA_MODEL",
            "llama.cpp": "ASTRA_AI_LLAMA_CPP_MODEL",
        }[provider]
        defaults = {
            "groq": self.DEFAULT_GROQ_MODEL,
            "gemini": self.DEFAULT_GEMINI_MODEL,
            "ollama": self.DEFAULT_OLLAMA_MODEL,
            "llama.cpp": self.DEFAULT_LLAMA_CPP_MODEL,
        }
        return os.getenv(env_name, defaults[provider])

    def _validate_messages(self, messages: Sequence[dict[str, str]]) -> int:
        if not messages:
            raise ResourceError("AI requests require at least one message.")
        total = 0
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ResourceError("AI messages must contain text content.")
            total += len(message["content"])
        if total > self.max_input_chars:
            raise ResourceError("AI input exceeds the configured size limit.")
        return total

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
        selected_provider = (provider or self.provider_name).lower()
        adapter = self._provider(selected_provider)
        selected_model = self._model(selected_provider, model)
        try:
            async with self._semaphore:
                text = await adapter.chat(
                    messages,
                    model=selected_model,
                    temperature=temperature,
                    max_output_tokens=self.max_output_tokens,
                    timeout=self.timeout,
                )
        except asyncio.TimeoutError as exc:
            raise TimeoutError("AI request timed out.") from exc
        if len(text) > self.max_output_chars:
            text = text[: self.max_output_chars].rstrip()
        return AIResponse(text, selected_provider, selected_model, input_chars, len(text))

    async def summarize(self, text: str, *, model: str | None = None, provider: str | None = None) -> AIResponse:
        return await self.chat(
            [
                {
                    "role": "system",
                    "content": "You are a concise assistant. Provide a brief, bulleted summary of the following text, extracting only the most critical information.",
                },
                {"role": "user", "content": text},
            ],
            model=model,
            provider=provider,
        )

    async def extract(
        self,
        text: str,
        instruction: str,
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> AIResponse:
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

    async def classify(
        self,
        text: str,
        labels: Sequence[str],
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> AIResponse:
        clean_labels = [label.strip() for label in labels if label.strip()]
        if not clean_labels or len(clean_labels) > 100:
            raise ResourceError("Classification requires between 1 and 100 labels.")
        return await self.chat(
            [
                {"role": "system", "content": "Return exactly one label from the allowed list and nothing else."},
                {"role": "user", "content": f"Allowed labels: {', '.join(clean_labels)}\n\nText:\n{text}"},
            ],
            model=model,
            provider=provider,
            temperature=0.0,
        )

    async def transcribe(
        self,
        file_path: str,
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> AIResponse:
        selected_provider = (provider or self.provider_name).lower()
        adapter = self._provider(selected_provider)
        if not adapter.supports_transcription:
            raise ConfigurationError(f"AI provider '{selected_provider}' does not support transcription.")
        path = Path(file_path)
        if not path.is_file():
            raise ResourceError("The audio file does not exist.")
        max_audio_bytes = int(os.getenv("ASTRA_AI_MAX_AUDIO_BYTES", str(100 * 1024 * 1024)))
        if path.stat().st_size <= 0 or path.stat().st_size > max_audio_bytes:
            raise ResourceError("Audio file exceeds the configured AI size limit.")
        selected_model = self._model(selected_provider, model, transcription=True)
        async with self._semaphore:
            text = await adapter.transcribe(str(path), model=selected_model, timeout=self.timeout)
        if len(text) > self.max_output_chars:
            text = text[: self.max_output_chars].rstrip()
        return AIResponse(text, selected_provider, selected_model, 0, len(text))
