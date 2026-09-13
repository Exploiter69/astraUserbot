import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.errors import ConfigurationError, ExternalServiceError, ResourceError, TimeoutError
from core.services.ai import AIService, GeminiProvider, GroqProvider, OllamaProvider
from core.services.http import HttpResponse


class FakeProvider:
    name = "fake"
    supports_transcription = True
    is_remote = False

    def __init__(self):
        self.calls = []
        self.active = 0
        self.maximum_active = 0

    async def chat(self, messages, *, model, temperature, max_output_tokens, timeout):
        self.calls.append((messages, model, temperature, max_output_tokens, timeout))
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return "fake response"
        finally:
            self.active -= 1

    async def transcribe(self, file_path, *, model, timeout):
        self.calls.append((file_path, model, timeout))
        return "fake transcript"


class FailingProvider(FakeProvider):
    is_remote = True

    async def chat(self, *args, **kwargs):
        raise ExternalServiceError("provider failed")


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class AIGatewayTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, provider=None, **kwargs):
        service = AIService(object(), provider="groq", fallback_providers=(), **kwargs)
        fake = provider or FakeProvider()
        service._providers["fake"] = fake
        service.provider_name = "fake"
        return service, fake

    async def test_chat_returns_provider_neutral_response(self):
        service, fake = self.make_service()
        response = await service.chat([{"role": "user", "content": "hello"}], model="test-model")
        self.assertEqual(response.text, "fake response")
        self.assertEqual(response.provider, "fake")
        self.assertEqual(response.model, "test-model")
        self.assertEqual(response.input_chars, 5)
        self.assertEqual(response.output_chars, len("fake response"))
        self.assertEqual(len(fake.calls), 1)

    async def test_summarize_is_gateway_owned(self):
        service, fake = self.make_service()
        await service.summarize("long text")
        messages = fake.calls[0][0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("brief, bulleted summary", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "long text")

    async def test_extract_and_classify_use_zero_temperature(self):
        service, fake = self.make_service()
        await service.extract("abc", "find names")
        await service.classify("abc", ["one", "two"])
        self.assertEqual(fake.calls[0][2], 0.0)
        self.assertEqual(fake.calls[1][2], 0.0)

    async def test_input_bound_is_enforced(self):
        service, _ = self.make_service(max_input_chars=4)
        with self.assertRaises(ResourceError):
            await service.chat([{"role": "user", "content": "12345"}])

    async def test_message_shape_and_count_are_bounded(self):
        service, _ = self.make_service()
        with self.assertRaises(ResourceError):
            await service.chat([{"role": "user", "content": "x", "tool": "bad"}])
        with self.assertRaises(ResourceError):
            await service.chat([{"role": "user", "content": "x"}] * 65)
        with self.assertRaises(ResourceError):
            await service.chat([{"role": "user", "content": "x" * 50_001}])

    async def test_output_is_bounded(self):
        fake = FakeProvider()

        async def long_chat(*args, **kwargs):
            return "x" * 20

        fake.chat = long_chat
        service, _ = self.make_service(provider=fake, max_output_chars=7)
        response = await service.chat([{"role": "user", "content": "x"}])
        self.assertEqual(response.text, "xxxxxxx")

    async def test_provider_selection_includes_local_ollama(self):
        service, _ = self.make_service()
        self.assertIn("groq", service.available_providers)
        self.assertIn("gemini", service.available_providers)
        self.assertIn("ollama", service.available_providers)
        self.assertEqual(service.provider_modes["ollama"], "local")
        self.assertEqual(service.provider_modes["groq"], "remote")

    async def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            AIService(object(), provider="does-not-exist")

    async def test_unknown_fallback_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            AIService(object(), provider="groq", fallback_providers=("does-not-exist",))

    async def test_fallback_is_used_for_provider_failure(self):
        service = AIService(object(), provider="first", fallback_providers=("second",))
        first = FailingProvider()
        second = FakeProvider()
        service._providers = {"first": first, "second": second}
        response = await service.chat([{"role": "user", "content": "hello"}])
        self.assertEqual(response.provider, "second")
        self.assertEqual(response.text, "fake response")

    async def test_fallback_does_not_swallow_cancellation(self):
        class SlowProvider(FakeProvider):
            async def chat(self, *args, **kwargs):
                await asyncio.sleep(10)
                return "never"

        service = AIService(object(), provider="slow", fallback_providers=("fake",))
        service._providers = {"slow": SlowProvider(), "fake": FakeProvider()}
        task = asyncio.create_task(service.chat([{"role": "user", "content": "x"}]))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_explicit_provider_does_not_fallback(self):
        service = AIService(object(), provider="first", fallback_providers=("second",))
        service._providers = {"first": FailingProvider(), "second": FakeProvider()}
        with self.assertRaises(ExternalServiceError):
            await service.chat([{"role": "user", "content": "hello"}], provider="first")

    async def test_remote_budget_blocks_before_request(self):
        service = AIService(object(), provider="groq", fallback_providers=(), max_remote_requests=1)
        fake = FailingProvider()
        service._providers["groq"] = fake
        with self.assertRaises(ExternalServiceError):
            await service.chat([{"role": "user", "content": "one"}])
        with self.assertRaises(ResourceError):
            await service.chat([{"role": "user", "content": "two"}])

    async def test_remote_disabled_allows_local_fallback(self):
        service = AIService(object(), provider="groq", fallback_providers=("ollama",))
        service.remote_enabled = False
        local = FakeProvider()
        service._providers["ollama"] = local
        response = await service.chat([{"role": "user", "content": "hello"}])
        self.assertEqual(response.provider, "ollama")

    async def test_tool_calls_are_rejected(self):
        response = HttpResponse(
            200, {}, json.dumps({"choices": [{"message": {"content": "", "tool_calls": [{"id": "1"}]}}]}).encode(), "https://example.test/chat/completions"
        )
        provider = GroqProvider(FakeHttp(response), "secret")
        with self.assertRaises(ExternalServiceError):
            await provider.chat(
                [{"role": "user", "content": "hello"}], model="model", temperature=0.7, max_output_tokens=100, timeout=1
            )

    async def test_transcription_capability_is_enforced(self):
        service, _ = self.make_service()
        service._providers["no-transcribe"] = GeminiProvider(object(), "secret")
        with tempfile.NamedTemporaryFile(suffix=".ogg") as handle:
            handle.write(b"audio")
            handle.flush()
            with self.assertRaises(ConfigurationError):
                await service.transcribe(handle.name, provider="no-transcribe")

    async def test_transcription_is_bounded_and_provider_neutral(self):
        service, fake = self.make_service()
        with tempfile.NamedTemporaryFile(suffix=".ogg") as handle:
            handle.write(b"audio")
            handle.flush()
            response = await service.transcribe(handle.name)
        self.assertEqual(response.text, "fake transcript")
        self.assertEqual(response.provider, "fake")
        self.assertEqual(response.input_chars, 0)
        self.assertEqual(fake.calls[0][1], service.DEFAULT_TRANSCRIBE_MODEL)

    async def test_audio_size_bound_is_enforced(self):
        service, _ = self.make_service()
        with tempfile.NamedTemporaryFile(suffix=".ogg") as handle:
            handle.write(b"audio")
            handle.flush()
            with patch.dict(os.environ, {"ASTRA_AI_MAX_AUDIO_BYTES": "2"}):
                with self.assertRaises(ResourceError):
                    await service.transcribe(handle.name)

    async def test_cancellation_propagates(self):
        class SlowProvider(FakeProvider):
            async def chat(self, *args, **kwargs):
                await asyncio.sleep(10)
                return "never"

        service, _ = self.make_service(provider=SlowProvider())
        task = asyncio.create_task(service.chat([{"role": "user", "content": "x"}]))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_timeout_is_bounded(self):
        class SlowProvider(FakeProvider):
            async def chat(self, *args, **kwargs):
                await asyncio.sleep(10)
                return "never"

        service, _ = self.make_service(provider=SlowProvider(), timeout=0.01)
        with self.assertRaises(TimeoutError):
            await service.chat([{"role": "user", "content": "x"}])

    async def test_concurrency_is_bounded(self):
        service, fake = self.make_service(concurrency=2)
        await asyncio.gather(*[service.chat([{"role": "user", "content": str(index)}]) for index in range(6)])
        self.assertLessEqual(fake.maximum_active, 2)

    async def test_groq_chat_adapter_parses_openai_response(self):
        response = HttpResponse(
            200, {}, json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode(), "https://api.groq.com/openai/v1/chat/completions"
        )
        http = FakeHttp(response)
        provider = GroqProvider(http, "secret")
        text = await provider.chat(
            [{"role": "user", "content": "hello"}], model="model", temperature=0.7, max_output_tokens=100, timeout=1
        )
        self.assertEqual(text, "hello")
        self.assertEqual(http.calls[0][1]["headers"]["Authorization"], "Bearer secret")

    async def test_groq_error_does_not_leak_provider_body(self):
        response = HttpResponse(
            401, {}, json.dumps({"error": {"message": "secret token details"}}).encode(), "https://api.groq.com/openai/v1/chat/completions"
        )
        provider = GroqProvider(FakeHttp(response), "secret")
        with self.assertRaises(ExternalServiceError) as raised:
            await provider.chat(
                [{"role": "user", "content": "hello"}], model="model", temperature=0.7, max_output_tokens=100, timeout=1
            )
        self.assertNotIn("secret token details", str(raised.exception))

    async def test_gemini_adapter_translates_messages(self):
        response = HttpResponse(
            200, {}, json.dumps({"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}).encode(), "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        )
        http = FakeHttp(response)
        provider = GeminiProvider(http, "secret")
        text = await provider.chat(
            [{"role": "system", "content": "be concise"}, {"role": "user", "content": "hello"}],
            model="gemini-2.5-flash", temperature=0.0, max_output_tokens=100, timeout=1,
        )
        self.assertEqual(text, "hello")
        payload = json.loads(http.calls[0][1]["data"])
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertIn("systemInstruction", payload)
        self.assertEqual(http.calls[0][1]["headers"]["x-goog-api-key"], "secret")
        self.assertNotIn("?key=secret", http.calls[0][0])

    async def test_ollama_adapter_parses_local_response(self):
        response = HttpResponse(
            200, {}, json.dumps({"message": {"content": "local hello"}}).encode(), "http://127.0.0.1:11434/api/chat"
        )
        http = FakeHttp(response)
        provider = OllamaProvider(http, "http://127.0.0.1:11434/api")
        text = await provider.chat(
            [{"role": "user", "content": "hello"}], model="local-model", temperature=0.0, max_output_tokens=100, timeout=1
        )
        self.assertEqual(text, "local hello")
        payload = json.loads(http.calls[0][1]["data"])
        self.assertFalse(payload["stream"])


if __name__ == "__main__":
    unittest.main()
