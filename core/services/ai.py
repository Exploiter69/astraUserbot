from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from core.errors import ConfigurationError, ExternalServiceError, ResourceError, TimeoutError
from core.services.http import HttpService

logger = logging.getLogger("astra.ai")


@dataclass(frozen=True)
class AIResponse:
    text: str
    provider: str
    model: str
    input_chars: int
    output_chars: int


class AIProvider(Protocol):
    name: str
    supports_transcription: bool
    is_remote: bool

    async def chat(self, messages, *, model: str, temperature: float, max_output_tokens: int, timeout: float) -> str: ...

    async def transcribe(self, file_path: str, *, model: str, timeout: float) -> str: ...


class _HTTPProvider:
    name = ""
    is_remote = True
    supports_transcription = False

    def __init__(self, http: HttpService, *, base_url: str, api_key: str):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def chat(self, messages, *, model, temperature, max_output_tokens, timeout):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        response = await self.http.request(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=timeout,
        )
        data = _json_object(response)
        return _chat_text(data)

    async def transcribe(self, file_path, *, model, timeout):
        raise ConfigurationError(f"AI provider '{self.name}' does not support transcription.")


class GroqProvider(_HTTPProvider):
    name = "groq"
    supports_transcription = True

    def __init__(self, http: HttpService, *, api_key: str):
        super().__init__(http, base_url="https://api.groq.com/openai/v1", api_key=api_key)
        self.transcription_model = os.getenv("ASTRA_AI_GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3")

    async def transcribe(self, file_path, *, model, timeout):
        response = await self.http.request(
            "POST",
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": (Path(file_path).name, Path(file_path).read_bytes())},
            data={"model": model},
            timeout=timeout,
        )
        data = _json_object(response)
        text = data.get("text")
        if not isinstance(text, str):
            raise ExternalServiceError("AI transcription response did not contain text.")
        return text


class GeminiProvider(_HTTPProvider):
    name = "gemini"

    def __init__(self, http: HttpService, *, api_key: str):
        self.api_key = api_key
        self.http = http
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def chat(self, messages, *, model, temperature, max_output_tokens, timeout):
        contents = []
        system_parts = []
        for message in messages:
            role = message["role"]
            content = message["content"]
            if role == "system":
                system_parts.append(content)
            else:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        response = await self.http.request(
            "POST",
            f"{self.base_url}/models/{model}:generateContent?key={self.api_key}",
            json=payload,
            timeout=timeout,
        )
        data = _json_object(response)
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalServiceError("Gemini response did not contain text.") from exc


class OllamaProvider:
    name = "ollama"
    is_remote = False
    supports_transcription = False

    def __init__(self, http: HttpService, *, base_url: str):
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def chat(self, messages, *, model, temperature, max_output_tokens, timeout):
        payload = {"model": model, "messages": messages, "stream": False, "options": {"temperature": temperature}}
        response = await self.http.request("POST", f"{self.base_url}/api/chat", json=payload, timeout=timeout)
        data = _json_object(response)
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ExternalServiceError("Ollama response did not contain text.") from exc

    async def transcribe(self, file_path, *, model, timeout):
        raise ConfigurationError("Ollama transcription is not available in the AI gateway.")


def _json_object(response):
    data = response.json()
    if not isinstance(data, dict):
        raise ExternalServiceError("AI provider returned an invalid response.")
    return data


def _chat_text(data):
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExternalServiceError("AI provider response did not contain text.") from exc
    if not isinstance(text, str):
        raise ExternalServiceError("AI provider response contained non-text content.")
    return text


class AIService:
    def __init__(self, http: HttpService):
        self.provider_name = os.getenv("ASTRA_AI_PROVIDER", "groq").lower()
        self.fallback_providers = tuple(p.strip().lower() for p in os.getenv("ASTRA_AI_FALLBACKS", "gemini,ollama").split(",") if p.strip())
        self.max_input_chars = int(os.getenv("ASTRA_AI_MAX_INPUT_CHARS", "100000"))
        self.max_output_chars = int(os.getenv("ASTRA_AI_MAX_OUTPUT_CHARS", "30000"))
        self.max_output_tokens = int(os.getenv("ASTRA_AI_MAX_OUTPUT_TOKENS", "8192"))
        self.max_messages = int(os.getenv("ASTRA_AI_MAX_MESSAGES", "64"))
        self.max_message_chars = int(os.getenv("ASTRA_AI_MAX_MESSAGE_CHARS", "50000"))
        self.concurrency = int(os.getenv("ASTRA_AI_CONCURRENCY", "2"))
        self.timeout = float(os.getenv("ASTRA_AI_TIMEOUT", "90"))
        self.remote_enabled = os.getenv("ASTRA_AI_REMOTE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        self.max_remote_requests = int(os.getenv("ASTRA_AI_MAX_REMOTE_REQUESTS", "100"))
        self.remote_window_seconds = int(os.getenv("ASTRA_AI_REMOTE_WINDOW_SECONDS", str(86400)))
        self._remote_requests = deque()
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._providers = {
            "groq": GroqProvider(http, api_key=os.getenv("GROQ_API_KEY", "")) if os.getenv("GROQ_API_KEY") else None,
            "gemini": GeminiProvider(http, api_key=os.getenv("GEMINI_API_KEY", "")) if os.getenv("GEMINI_API_KEY") else None,
            "ollama": OllamaProvider(http, base_url=os.getenv("ASTRA_AI_OLLAMA_URL", "http://127.0.0.1:11434")),
        }
        if self.provider_name not in self._providers:
            raise ConfigurationError(f"Unknown AI provider '{self.provider_name}'.")
        for provider in self.fallback_providers:
            if provider not in self._providers:
                raise ConfigurationError(f"Unknown AI fallback provider '{provider}'.")

    @property
    def available_providers(self):
        return tuple(name for name, provider in self._providers.items() if provider is not None)

    @property
    def capabilities(self):
        return {
            "chat": True,
            "summarize": True,
            "extract": True,
            "classify": True,
            "transcribe": any(p is not None and p.supports_transcription for p in self._providers.values()),
        }

    @property
    def provider_modes(self):
        return {name: ("remote" if provider is not None and provider.is_remote else "local") for name, provider in self._providers.items() if provider is not None}

    def _provider(self, name):
        provider = self._providers.get(name)
        if provider is None:
            raise ConfigurationError(f"AI provider '{name}' is not configured.")
        return provider

    def _model(self, provider, model, *, transcription=False):
        if model:
            return model
        if provider == "groq":
            return os.getenv("ASTRA_AI_GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3") if transcription else os.getenv("ASTRA_AI_GROQ_MODEL", "openai/gpt-oss-20b")
        if provider == "gemini":
            return os.getenv("ASTRA_AI_GEMINI_MODEL", "gemini-2.5-flash")
        return os.getenv("ASTRA_AI_OLLAMA_MODEL", "qwen2.5:7b")

    def _validate_messages(self, messages):
        if not isinstance(messages, list) or not messages or len(messages) > self.max_messages:
            raise ResourceError("AI request exceeds the configured message limit.")
        total = 0
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"} or not isinstance(message.get("content"), str):
                raise ResourceError("AI messages must contain valid roles and text content.")
            if len(message["content"]) > self.max_message_chars:
                raise ResourceError("AI message exceeds the configured size limit.")
            total += len(message["content"])
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
        last_error = None
        for index, provider_name in enumerate(self._candidates(provider)):
            try:
                response = await self._chat_once(provider_name, messages, model=model, temperature=temperature)
                return AIResponse(response.text, response.provider, response.model, input_chars, response.output_chars)
            except asyncio.CancelledError:
                raise
            except (ConfigurationError, ExternalServiceError, TimeoutError) as exc:
                last_error = exc
                if provider is not None or index == len(self._candidates(provider)) - 1:
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
        # Transcription has no textual prompt input. input_chars therefore
        # represents prompt/context characters only, not the binary file size.
        return AIResponse(text, selected_provider, selected_model, 0, len(text))
