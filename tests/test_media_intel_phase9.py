import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from core.services.cases import CaseService
from core.services.media_intel import MediaIntelService


class FakeStorage:
    def __init__(self):
        self.rows = []

    async def fetchall(self, query, params=()):
        return self.rows


class MediaIntelUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_hamming_and_similar_are_bounded(self):
        graph = type("Graph", (), {"storage": FakeStorage(), "start": AsyncMock()})()
        graph.storage.rows = [("a", "0000000000000000", "a"), ("b", "ffffffffffffffff", "b")]
        service = MediaIntelService(object(), graph)
        matches = await service.similar("0000000000000000", limit=5000)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["distance"], 0)
        self.assertEqual(service._hamming("0", "0"), 0)

    async def test_sha256_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.bin"
            path.write_bytes(b"phase9")
            expected = hashlib.sha256(b"phase9").hexdigest()
            self.assertEqual(MediaIntelService._sha256(path), expected)


class CaseServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = type("DB", (), {})()
        self.db.init_schema = AsyncMock()
        self.db.execute = AsyncMock(side_effect=[type("Cursor", (), {"lastrowid": 1})(), None, None, None, None])
        self.db.fetchone = AsyncMock(return_value=None)
        self.db.fetchall = AsyncMock(return_value=[])
        graph = type("Graph", (), {"storage": self.db, "start": AsyncMock()})()
        self.service = CaseService(graph)
        self.service.db = self.db
        self.service._started = True

    async def test_create_persists_case_and_timeline(self):
        case_id = await self.service.create("Phase 9 case")
        self.assertTrue(case_id)
        self.assertGreaterEqual(self.db.execute.await_count, 2)

    async def test_report_is_deterministic_and_bounded(self):
        self.service.get = AsyncMock(return_value={"case_id": "abc", "title": "Test", "status": "OPEN", "summary": "summary"})
        self.service.entities = AsyncMock(return_value=[])
        self.service.timeline = AsyncMock(return_value=[])
        report = await self.service.report("abc")
        self.assertIn("CASE abc", report)
        self.assertLessEqual(len(report), 16000)

    async def test_missing_case_is_rejected(self):
        with self.assertRaises(ValueError):
            await self.service.add_timeline("missing", "NOTE", "x")


if __name__ == "__main__":
    unittest.main()
