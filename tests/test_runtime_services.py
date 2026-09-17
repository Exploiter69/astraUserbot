"""Runtime service lifecycle tests."""

import tempfile
import unittest

from core.context import ApplicationContext, get_application_context, set_application_context


class RuntimeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        context = get_application_context()
        if context is not None:
            await context.close()
        set_application_context(None)

    async def test_application_context_starts_and_closes_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp); set_application_context(context); await context.start()
            self.assertEqual(context.snapshot()["state"], "RUNNING")
            self.assertEqual(set(context.services), {"storage", "cache", "http", "subprocess", "telegram_state", "telegram", "telegram_event_journal", "telegram_events", "telegram_event_projections", "telegram_event_replay", "intelgraph", "public_intel", "workspace", "media", "jobs", "automation", "secrets", "ai", "search", "telegram_archive", "metrics", "flags", "isolation"})
            self.assertIsNotNone(context.get("http").session); self.assertTrue(context.get("cache").db_path.exists()); self.assertIsNotNone(context.get("storage").conn); self.assertTrue(context.get("workspace").root.exists())
            self.assertIs(context.get("media").workspace, context.get("workspace")); self.assertIn("groq", context.get("ai").available_providers); self.assertIn("gemini", context.get("ai").available_providers)
            self.assertTrue(context.get("search")._ready); self.assertTrue(context.get("flags")._started); self.assertTrue(context.get("isolation")._started); self.assertTrue(context.get("telegram_state")._started); self.assertTrue(context.get("telegram_event_journal")._started); self.assertTrue(context.get("telegram_events")._started); self.assertTrue(context.get("telegram_event_projections")._started); self.assertTrue(context.get("telegram_event_replay")._started); self.assertTrue(context.get("intelgraph")._started); self.assertTrue(context.get("telegram_archive")._started)
            await context.close(); self.assertEqual(context.snapshot()["state"], "CLOSED"); self.assertIsNone(context.get("http").session)

    async def test_context_rejects_duplicate_service_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ApplicationContext(object(), tmp)
            with self.assertRaises(ValueError):
                context.register("storage", object())
            await context.close()
