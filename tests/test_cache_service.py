import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from core.services.cache import CacheService


class CacheServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.service = CacheService(
            self.tmp.name,
            max_l1_entries=1,
            max_l1_bytes=128,
            max_l2_entries=4,
            max_l2_bytes=512,
            max_artifact_entries=2,
            max_artifact_bytes=16,
            max_value_bytes=128,
            max_artifact_bytes_per_item=16,
        )
        await self.service.start()

    async def asyncTearDown(self) -> None:
        await self.service.close()
        self.tmp.cleanup()

    async def test_json_value_round_trip_and_metadata(self) -> None:
        await self.service.set("http", "item", {"answer": 42}, ttl=60, source="test", content_type="application/json")
        entry = await self.service.get("http", "item")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.value, {"answer": 42})
        self.assertEqual(entry.source, "test")
        self.assertEqual(entry.content_type, "application/json")

    async def test_l2_survives_l1_eviction_and_restart(self) -> None:
        await self.service.set("a", "one", {"n": 1})
        await self.service.set("a", "two", {"n": 2})
        first = await self.service.get("a", "one")
        self.assertEqual(first.value if first else None, {"n": 1})
        await self.service.close()

        restarted = CacheService(self.tmp.name, max_l1_entries=1, max_l1_bytes=128, max_value_bytes=128)
        await restarted.start()
        entry = await restarted.get("a", "two")
        self.assertEqual(entry.value if entry else None, {"n": 2})
        await restarted.close()

    async def test_ttl_expires_from_l1_and_l2(self) -> None:
        await self.service.set("ttl", "short", "value", ttl=0.03)
        await asyncio.sleep(0.06)
        self.assertIsNone(await self.service.get("ttl", "short"))
        stats = await self.service.stats()
        self.assertGreaterEqual(stats.misses, 1)

    async def test_version_and_namespace_isolation(self) -> None:
        await self.service.set("n1", "same", "v1", version="1")
        await self.service.set("n1", "same", "v2", version="2")
        await self.service.set("n2", "same", "other", version="1")
        self.assertEqual((await self.service.get("n1", "same", version="1")).value, "v1")
        self.assertEqual((await self.service.get("n1", "same", version="2")).value, "v2")
        self.assertEqual((await self.service.get("n2", "same")).value, "other")
        await self.service.invalidate_namespace("n1")
        self.assertIsNone(await self.service.get("n1", "same", version="1"))
        self.assertIsNotNone(await self.service.get("n2", "same"))

    async def test_l1_and_l2_limits_are_bounded(self) -> None:
        for index in range(10):
            await self.service.set("limit", str(index), "x" * 40)
        stats = await self.service.stats()
        self.assertLessEqual(stats.l1_entries, 1)
        self.assertLessEqual(stats.l1_bytes, 128)
        self.assertLessEqual(stats.l2_entries, 4)
        self.assertLessEqual(stats.l2_bytes, 512)

    async def test_get_or_set_serializes_same_key(self) -> None:
        calls = 0
        lock = asyncio.Lock()

        async def factory() -> dict[str, int]:
            nonlocal calls
            async with lock:
                calls += 1
            await asyncio.sleep(0.02)
            return {"value": 7}

        entries = await asyncio.gather(*[
            self.service.get_or_set("stampede", "key", factory, ttl=60)
            for _ in range(8)
        ])
        self.assertEqual(calls, 1)
        self.assertTrue(all(entry.value == {"value": 7} for entry in entries))

    async def test_artifact_round_trip_and_metadata(self) -> None:
        payload = b"binary-payload"
        artifact = await self.service.put_artifact("media", "clip", payload, content_type="video/test", ttl=60)
        self.assertTrue(artifact.path.is_file())
        self.assertEqual(artifact.size, len(payload))
        self.assertEqual(await self.service.read_artifact("media", "clip"), payload)
        fetched = await self.service.get_artifact("media", "clip")
        self.assertEqual(fetched.content_type if fetched else None, "video/test")

    async def test_artifact_limit_evicts_oldest(self) -> None:
        await self.service.put_artifact("media", "a", b"12345678")
        await asyncio.sleep(0.01)
        await self.service.put_artifact("media", "b", b"abcdefgh")
        await asyncio.sleep(0.01)
        await self.service.put_artifact("media", "c", b"ABCDEFGH")
        stats = await self.service.stats()
        self.assertLessEqual(stats.artifact_entries, 2)
        self.assertLessEqual(stats.artifact_bytes, 16)
        self.assertIsNone(await self.service.get_artifact("media", "a"))

    async def test_artifact_path_metadata_is_contained(self) -> None:
        artifact = await self.service.put_artifact("safe", "key", b"x")
        self.assertTrue(Path(artifact.path).resolve().is_relative_to(self.service.artifact_root))

    async def test_clear_removes_values_and_artifacts(self) -> None:
        await self.service.set("clear", "value", 1)
        await self.service.put_artifact("clear", "artifact", b"x")
        await self.service.clear()
        self.assertIsNone(await self.service.get("clear", "value"))
        self.assertIsNone(await self.service.get_artifact("clear", "artifact"))
        self.assertEqual((await self.service.stats()).l2_entries, 0)

    async def test_cleanup_removes_expired_artifacts(self) -> None:
        artifact = await self.service.put_artifact("ttl", "artifact", b"x", ttl=0.02)
        await asyncio.sleep(0.05)
        await self.service.cleanup()
        self.assertFalse(artifact.path.exists())
        self.assertIsNone(await self.service.get_artifact("ttl", "artifact"))

    async def test_stats_track_hits_and_misses(self) -> None:
        await self.service.set("stats", "hit", True)
        await self.service.get("stats", "hit")
        await self.service.get("stats", "missing")
        stats = await self.service.stats()
        self.assertGreaterEqual(stats.hits, 1)
        self.assertGreaterEqual(stats.misses, 1)


if __name__ == "__main__":
    unittest.main()
