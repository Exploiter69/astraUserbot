from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from core.services.flags import FeatureFlagService
from core.services.isolation import IsolationService
from core.services.metrics import MetricsService
from core.services.search import SearchService
from core.services.storage import StorageService
from core.sdk import SDK_API_VERSION, metadata


class Phase10To15Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = StorageService(self.root)
        await self.storage.start()

    async def asyncTearDown(self):
        await self.storage.close()
        self.tmp.cleanup()

    async def test_search_rebuild_and_query(self):
        service = SearchService(self.storage, self.root)
        await service.start()
        await self.storage.execute("INSERT INTO plugins(name,module,state,updated_at) VALUES(?,?,?,?)", ("demo", "plugins.demo", "RUNNING", 1))
        await service.rebuild()
        results = await service.search("demo")
        self.assertTrue(any(item.source == "plugin" for item in results))
        await service.close()

    async def test_search_is_rebuildable(self):
        service = SearchService(self.storage, self.root)
        await service.start()
        await service.upsert(source="document", ref="x.md", title="X", content="rebuildable source")
        self.assertTrue(await service.search("rebuildable"))
        await service.rebuild()
        self.assertFalse(await service.search("rebuildable"))
        await service.upsert(source="document", ref="x.md", title="X", content="rebuildable source")
        self.assertTrue(await service.search("rebuildable"))
        await service.close()

    async def test_flags_persist(self):
        flags = FeatureFlagService(self.storage)
        await flags.start()
        await flags.set("phase15", True)
        self.assertTrue(await flags.enabled("phase15"))
        self.assertEqual((await flags.list())[0]["name"], "phase15")
        await flags.close()

    async def test_metrics_are_bounded_and_report_resources(self):
        metrics = MetricsService(self.root)
        await metrics.start()
        metrics.increment("tests")
        with metrics.timer("latency"):
            await asyncio.sleep(0)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot.counters["tests"], 1)
        self.assertIn("latency", snapshot.timings)
        self.assertIn("rss_bytes", snapshot.resources)
        await metrics.close()

    async def test_isolation_is_explicit(self):
        service = IsolationService()
        await service.start()
        assessment = service.assess()
        self.assertFalse(assessment.enabled)
        self.assertIn("opt-in", assessment.reason)
        await service.close()

    def test_sdk_metadata_contract(self):
        item = metadata(name="example", version="1.2.3", capabilities=("network.request",))
        self.assertEqual(item.api_version, SDK_API_VERSION)
        with self.assertRaises(ValueError):
            metadata(name="bad", api_version="99.0")


if __name__ == "__main__":
    unittest.main()
