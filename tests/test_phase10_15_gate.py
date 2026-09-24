from __future__ import annotations

import asyncio
import shutil
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

    async def test_search_cursor_is_opaque_and_stable_for_same_query(self):
        service = SearchService(self.storage, self.root)
        await service.start()
        for index in range(3):
            await service.upsert(source="document", ref=f"{index}.md", title=f"alpha {index}", content="alpha evidence")
        first = await service.search_page("alpha", limit=1)
        self.assertEqual(len(first.results), 1)
        self.assertTrue(first.next_cursor)
        second = await service.search_page("alpha", limit=1, cursor=first.next_cursor)
        self.assertEqual(len(second.results), 1)
        self.assertNotEqual(first.results[0].result_id, second.results[0].result_id)
        with self.assertRaises(ValueError):
            await service.search_page("different", limit=1, cursor=first.next_cursor)
        await service.close()

    async def test_search_rebuild_indexes_ocr_and_transcript_evidence(self):
        service = SearchService(self.storage, self.root)
        await service.start()
        now = 1.0
        await self.storage.execute(
            "INSERT INTO intel_entities(entity_id,entity_type,canonical_value,display_value,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("ocr-entity", "TEXT", "invoice account 123", "invoice account 123", now, now),
        )
        await self.storage.execute(
            "INSERT INTO intel_entities(entity_id,entity_type,canonical_value,display_value,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("transcript-entity", "TEXT", "spoken phrase 456", "spoken phrase 456", now, now),
        )
        await self.storage.execute(
            "INSERT INTO intel_sources(source_id,source_family,provider,source_type,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("media-source", "media", "test", "local", now, now),
        )
        await self.storage.execute(
            "INSERT INTO intel_observations(observation_id,entity_id,source_id,source_family,retrieved_at,matched_field,evidence_state,confidence,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)",
            ("ocr-obs", "ocr-entity", "media-source", "media", now, "ocr_text", "OBSERVED", 0.9, "{}"),
        )
        await self.storage.execute(
            "INSERT INTO intel_observations(observation_id,entity_id,source_id,source_family,retrieved_at,matched_field,evidence_state,confidence,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)",
            ("transcript-obs", "transcript-entity", "media-source", "media", now, "transcript", "OBSERVED", 0.9, "{}"),
        )
        counts = await service.rebuild()
        self.assertGreaterEqual(counts["ocr"], 1)
        self.assertGreaterEqual(counts["transcript"], 1)
        self.assertTrue(await service.search("invoice"))
        self.assertTrue(await service.search("spoken"))
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

    async def test_isolation_backend_is_explicit(self):
        service = IsolationService()
        await service.start()
        assessment = service.assess()
        self.assertEqual(assessment.enabled, bool(shutil.which("bwrap")))
        self.assertIn("Bubblewrap", assessment.reason)
        await service.close()

    def test_sdk_metadata_contract(self):
        item = metadata(name="example", version="1.2.3", capabilities=("network.request",))
        self.assertEqual(item.api_version, SDK_API_VERSION)
        with self.assertRaises(ValueError):
            metadata(name="bad", api_version="99.0")


if __name__ == "__main__":
    unittest.main()
