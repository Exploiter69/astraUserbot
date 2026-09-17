"""Phase 16 runtime lifecycle gate tests."""

import asyncio
import unittest

from core.context import ApplicationContext

ROOT = "/tmp/astra-phase16-gate"


class Phase16Gate(unittest.TestCase):
    def test_application_context_runtime_lifecycle(self):
        async def run():
            context = ApplicationContext(object(), ROOT)
            expected = {
                "storage", "cache", "http", "subprocess", "telegram_state", "telegram",
                "telegram_event_journal", "telegram_events", "telegram_event_projections", "telegram_event_replay", "intelgraph",
                "public_intel", "telegram_archive", "workspace", "media", "jobs", "automation", "secrets", "ai", "search", "metrics", "flags", "isolation",
            }
            self.assertEqual(set(context.services), expected)
            await context.start()
            self.assertEqual(context.snapshot()["state"], "RUNNING")
            await context.close()
            self.assertEqual(context.snapshot()["state"], "CLOSED")
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
