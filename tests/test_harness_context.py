import tempfile
import unittest
from unittest.mock import patch

from core.context import ApplicationContext
from core.services.http import HttpResponse, HttpService


class SubstituteHttp:
    def __init__(self):
        self.started = 0
        self.closed = 0

    async def start(self):
        self.started += 1

    async def close(self):
        self.closed += 1

    async def request(self, method, url, **kwargs):
        return HttpResponse(200, {"content-type": "text/plain"}, b"canned", url)

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self.request("POST", url, **kwargs)


class HarnessContextAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_override_is_installed_before_dependents_and_only_it_is_started_closed(self):
        from astra.testing.context import HarnessApplicationContext

        constructed_defaults = []

        class TrackedDefaultHttp(HttpService):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.start_calls = 0
                self.close_calls = 0
                constructed_defaults.append(self)

            async def start(self):
                self.start_calls += 1
                return await super().start()

            async def close(self):
                self.close_calls += 1
                await super().close()

        substitute = SubstituteHttp()
        with tempfile.TemporaryDirectory() as root:
            with patch("core.context.HttpService", TrackedDefaultHttp):
                context = HarnessApplicationContext(
                    object(), root, service_overrides={"http": substitute}
                )
                self.assertIs(context.get("http"), substitute)
                self.assertIs(context.get("public_intel").http, substitute)
                self.assertIs(context.get("security_intel").http, substitute)
                self.assertIs(context.get("ai").http, substitute)
                self.assertEqual(len(constructed_defaults), 1)
                self.assertEqual(constructed_defaults[0].start_calls, 0)

                await context.start()
                self.assertEqual(substitute.started, 1)
                self.assertEqual(constructed_defaults[0].start_calls, 0)
                await context.close()

                self.assertEqual(substitute.closed, 1)
                self.assertEqual(constructed_defaults[0].close_calls, 0)
                self.assertIsNone(constructed_defaults[0].session)

    async def test_plain_application_context_constructs_its_own_http_service(self):
        with tempfile.TemporaryDirectory() as root:
            context = ApplicationContext(object(), root)
            http = context.get("http")
            self.assertIsInstance(http, HttpService)
            await context.start()
            self.assertIsNotNone(http.session)
            await context.close()
            self.assertIsNone(http.session)


if __name__ == "__main__":
    unittest.main()
