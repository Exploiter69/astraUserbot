import asyncio
import tempfile
import unittest

from aiohttp import web

from core.context import ApplicationContext, get_application_context, set_application_context
from core.errors import ErrorCode, ResourceError, TimeoutError
from core.services.http import HttpService
from core.services.subprocess import SubprocessService
from core.services.telegram import TelegramFacade
from core.services.workspace import WorkspaceService


class FakeTelegram:
    def __init__(self):
        self.calls = []

    async def send_message(self, entity, message, **kwargs):
        self.calls.append(("send_message", entity, message, kwargs))
        return "sent"

    async def send_file(self, entity, file, **kwargs):
        self.calls.append(("send_file", entity, file, kwargs))
        return "file"

    async def edit_message(self, entity, message, text, **kwargs):
        self.calls.append(("edit_message", entity, message, text, kwargs))
        return "edited"

    async def delete_messages(self, entity, message_ids, **kwargs):
        self.calls.append(("delete_messages", entity, message_ids, kwargs))
        return "deleted"

    async def get_entity(self, entity):
        return entity


class RuntimeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        set_application_context(None)

    async def asyncTearDown(self):
        context = get_application_context()
        if context is not None:
            await context.close()
        set_application_context(None)

    async def test_application_context_starts_and_closes_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()

            self.assertEqual(context.snapshot()["state"], "RUNNING")
            self.assertEqual(
                set(context.services),
                {"storage", "cache", "http", "subprocess", "telegram", "workspace", "media", "jobs", "secrets", "ai", "search", "metrics", "flags", "isolation"},
            )
            self.assertIsNotNone(context.get("http").session)
            self.assertTrue(context.get("cache").db_path.exists())
            self.assertIsNotNone(context.get("storage").conn)
            self.assertTrue(context.get("workspace").root.exists())
            self.assertIs(context.get("media").workspace, context.get("workspace"))
            self.assertIn("groq", context.get("ai").available_providers)
            self.assertIn("gemini", context.get("ai").available_providers)
            self.assertTrue(context.get("search")._ready)
            self.assertTrue(context.get("flags")._started)
            self.assertTrue(context.get("isolation")._started)

            await context.close()
            self.assertEqual(context.snapshot()["state"], "CLOSED")
            self.assertIsNone(context.get("http").session)

    async def test_context_rejects_duplicate_service_names(self):
        context = ApplicationContext(object(), tempfile.gettempdir())
        with self.assertRaises(ValueError):
            context.register("http", object())
        await context.close()

    async def test_subprocess_uses_argv_and_bounds_output(self):
        service = SubprocessService(default_output_bytes=8)
        result = await service.run(["python", "-c", "print('123456789012345')"])
        self.assertEqual(result.returncode, -15)
        self.assertLessEqual(len(result.stdout.encode()), 8)
        self.assertTrue(result.stdout_truncated)

    async def test_subprocess_timeout_is_controlled(self):
        service = SubprocessService()
        with self.assertRaises(TimeoutError) as raised:
            await service.run(["python", "-c", "import time; time.sleep(5)"], timeout=0.05)
        self.assertEqual(raised.exception.code, ErrorCode.TIMEOUT)

    async def test_workspace_isolated_and_path_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = WorkspaceService(tmp, max_file_bytes=8)
            workspace = await service.create("download")
            self.assertTrue(workspace.path.is_dir())
            self.assertEqual(workspace.resolve("output.bin").parent, workspace.path)
            with self.assertRaises(ValueError):
                workspace.resolve("../../escape")

            output = workspace.resolve("output.bin")
            output.write_bytes(b"123456789")
            with self.assertRaises(ResourceError):
                service.validate_file(output)
            await service.cleanup(workspace)
            self.assertFalse(workspace.path.exists())

    async def test_telegram_facade_preserves_raw_client_access(self):
        client = FakeTelegram()
        facade = TelegramFacade(client, retries=0)
        result = await facade.send_message("me", "hello", parse_mode="html")
        self.assertEqual(result, "sent")
        self.assertEqual(client.calls[0][0], "send_message")
        self.assertEqual(client.calls[0][3]["parse_mode"], "html")

    async def test_http_service_uses_shared_session_and_enforces_response_limit(self):
        async def handler(_request):
            return web.Response(body=b"0123456789")

        app = web.Application()
        app.router.add_get("/", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        service = HttpService(response_limit=64, retries=0)
        try:
            response = await service.get(f"http://127.0.0.1:{port}/")
            self.assertEqual(response.status, 200)
            self.assertEqual(response.body, b"0123456789")
            with self.assertRaises(ResourceError):
                await service.get(f"http://127.0.0.1:{port}/", response_limit=4)
        finally:
            await service.close()
            await runner.cleanup()

    async def test_http_service_can_restart_after_close(self):
        service = HttpService(retries=0)
        first = await service.start()
        await service.close()
        second = await service.start()
        try:
            self.assertIsNot(first, second)
            self.assertFalse(second.closed)
        finally:
            await service.close()

    async def test_http_cancellation_does_not_leave_request_running(self):
        async def handler(_request):
            await asyncio.sleep(10)
            return web.Response(text="late")

        app = web.Application()
        app.router.add_get("/", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        service = HttpService(retries=0)
        task = asyncio.create_task(service.get(f"http://127.0.0.1:{port}/"))
        await asyncio.sleep(0.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await service.close()
        await runner.cleanup()
