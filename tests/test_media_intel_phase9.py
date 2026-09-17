import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from core.services.cases import CaseService
from core.services.media_intel import MediaIntelService
from plugins.intelligence.media_cases import _resolve_media


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

    async def test_perceptual_hash_helpers_are_16_hex_digits(self):
        pixels32 = bytes(range(256)) * 4
        ahash_pixels = bytes(pixels32[row * 32 + col] for row in range(0, 32, 4) for col in range(0, 32, 4))
        dhash_grid = bytearray()
        for row in range(8):
            for col in range(9):
                dhash_grid.append(pixels32[(row * 4) * 32 + min(col * 4, 31)])
        for value in (
            MediaIntelService._dct_phash(pixels32),
            MediaIntelService._ahash(ahash_pixels),
            MediaIntelService._dhash(bytes(dhash_grid)),
        ):
            self.assertRegex(value, r"^[0-9a-f]{16}$")

    async def test_media_command_resolves_reply_even_without_is_reply_flag(self):
        media = object()
        reply = type("Reply", (), {"media": media})()

        async def get_reply_message():
            return reply

        event = type("Event", (), {"media": None, "get_reply_message": get_reply_message})()
        self.assertIs(await _resolve_media(event), media)

    async def test_media_command_prefers_command_media(self):
        media = object()
        event = type("Event", (), {"media": media})()
        self.assertIs(await _resolve_media(event), media)


class CaseServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = type("Storage", (), {})()
        self.storage.execute = AsyncMock(return_value=type("Cursor", (), {"lastrowid": 1})())
        self.storage.fetchone = AsyncMock(return_value={"case_id": "case"})
        self.storage.fetchall = AsyncMock(return_value=[])
        graph = type("Graph", (), {"storage": self.storage, "start": AsyncMock()})()
        self.service = CaseService(graph)
        self.service._started = True

    async def test_create_persists_case_and_timeline(self):
        case_id = await self.service.create("Phase 9 case")
        self.assertTrue(case_id)
        self.assertEqual(self.storage.execute.await_count, 4)
        calls = self.storage.execute.await_args_list
        self.assertIn("INSERT INTO cases", calls[0].args[0])
        self.assertIn("INSERT INTO case_timeline", calls[1].args[0])
        self.assertIn("UPDATE cases SET updated_at", calls[2].args[0])
        self.assertIn("INSERT INTO case_events", calls[3].args[0])

    async def test_report_is_deterministic_and_bounded(self):
        self.service.get = AsyncMock(return_value={"case_id": "abc", "title": "Test", "status": "OPEN", "summary": "summary"})
        self.service.entities = AsyncMock(return_value=[])
        self.service.timeline = AsyncMock(return_value=[])
        self.service.observations = AsyncMock(return_value=[])
        self.service.sources = AsyncMock(return_value=[])
        self.storage.fetchall = AsyncMock(return_value=[])
        report = await self.service.report("abc")
        self.assertIn("CASE abc", report)
        self.assertIn("VERIFIED / DERIVED OBSERVATIONS", report)
        self.assertLessEqual(len(report), 16000)

    async def test_missing_case_is_rejected(self):
        self.service.get = AsyncMock(return_value=None)
        with self.assertRaises(ValueError):
            await self.service.add_timeline("missing", "NOTE", "x")


if __name__ == "__main__":
    unittest.main()
