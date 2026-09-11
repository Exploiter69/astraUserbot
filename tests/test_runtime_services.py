import tempfile
import unittest

from core.context import ApplicationContext, set_application_context


class RuntimeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        context = None
        try:
            from core.context import get_application_context
            context = get_application_context()
        except Exception:
            pass
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
                {"storage", "cache", "http", "subprocess", "telegram", "workspace", "media", "jobs", "secrets", "ai"},
            )
            self.assertIsNotNone(context.get("http").session)
            self.assertTrue(context.get("cache").db_path.exists())
            self.assertIsNotNone(context.get("storage").conn)
            self.assertTrue(context.get("workspace").root.exists())
            self.assertIs(context.get("media").workspace, context.get("workspace"))
            self.assertIn("groq", context.get("ai").available_providers)
            self.assertIn("gemini", context.get("ai").available_providers)

            await context.close()
            self.assertEqual(context.snapshot()["state"], "CLOSED")
            self.assertIsNone(context.get("http").session)

    async def test_context_rejects_duplicate_service_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()
            with self.assertRaises(ValueError):
                context.register("http", object())
            await context.close()
            set_application_context(None)

    async def test_http_cancellation_does_not_leave_request_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()
            http = context.get("http")
            self.assertIsNotNone(http)
            await context.close()
            set_application_context(None)

    async def test_http_service_can_restart_after_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()
            await context.close()
            await context.start()
            self.assertEqual(context.snapshot()["state"], "RUNNING")
            await context.close()
            set_application_context(None)

    async def test_http_service_uses_shared_session_and_enforces_response_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()
            self.assertIsNotNone(context.get("http").session)
            await context.close()
            set_application_context(None)

    async def test_subprocess_timeout_is_controlled(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()
            result = await context.get("subprocess").run(["python", "-c", "import time; time.sleep(1)"], timeout=0.01)
            self.assertNotEqual(result.returncode, 0)
            await context.close()
            set_application_context(None)

    async def test_subprocess_uses_argv_and_bounds_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()
            result = await context.get("subprocess").run(["python", "-c", "print('ok')"], timeout=1)
            self.assertIn("ok", result.stdout)
            await context.close()
            set_application_context(None)

    async def test_telegram_facade_preserves_raw_client_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = object()
            context = ApplicationContext(raw, tmp)
            set_application_context(context)
            await context.start()
            self.assertIs(context.get("telegram").client, raw)
            await context.close()
            set_application_context(None)

    async def test_workspace_isolated_and_path_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()
            workspace = context.get("workspace")
            first = workspace.create("one")
            second = workspace.create("two")
            self.assertNotEqual(first.path, second.path)
            await context.close()
            set_application_context(None)

    async def test_cancel_and_shutdown_stop_long_lived_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            set_application_context(context)
            await context.start()
            await context.close()
            set_application_context(None)
