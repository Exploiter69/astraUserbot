import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.services.storage import StorageService
from core.services.telegram_state import TelegramStateCache


class TelegramStateCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tempdir.name))
        await self.storage.start()
        self.cache = TelegramStateCache(
            self.storage,
            entity_ttl=0.05,
            dialog_ttl=0.05,
            max_entities=3,
            max_dialogs=2,
        )
        await self.cache.start()

    async def asyncTearDown(self) -> None:
        await self.cache.close()
        await self.storage.close()
        self.tempdir.cleanup()

    @staticmethod
    def entity(entity_id: int, username: str = "alice") -> SimpleNamespace:
        return SimpleNamespace(
            id=entity_id,
            access_hash=entity_id * 10,
            username=username,
            first_name="Alice",
            last_name="Example",
            title=None,
            photo=SimpleNamespace(photo_id=entity_id * 100),
        )

    @staticmethod
    def dialog(entity_id: int, title: str) -> SimpleNamespace:
        entity = SimpleNamespace(id=entity_id, username=None, title=title, first_name=None, last_name=None)
        message = SimpleNamespace(id=entity_id * 1000)
        return SimpleNamespace(entity=entity, message=message)

    async def test_entity_hit_avoids_second_resolution_and_persists_state(self):
        calls = 0
        entity = self.entity(7)

        async def resolver():
            nonlocal calls
            calls += 1
            return entity

        self.assertIs(await self.cache.resolve_entity("@Alice", resolver), entity)
        self.assertIs(await self.cache.resolve_entity("alice", resolver), entity)
        self.assertEqual(calls, 1)

        state = await self.cache.get_entity_state("@alice")
        self.assertIsNotNone(state)
        self.assertEqual(state.entity_id, 7)
        self.assertEqual(state.access_hash, 70)
        self.assertEqual(state.username, "alice")
        self.assertEqual(state.photo_id, "700")

    async def test_concurrent_entity_resolution_is_single_flight(self):
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()
        entity = self.entity(8)

        async def resolver():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return entity

        tasks = [asyncio.create_task(self.cache.resolve_entity("@alice", resolver)) for _ in range(8)]
        await started.wait()
        await asyncio.sleep(0.01)
        self.assertEqual(calls, 1)
        release.set()
        results = await asyncio.gather(*tasks)
        self.assertEqual(results, [entity] * 8)
        self.assertEqual(self.cache.snapshot()["inflight_joins"], 7)

    async def test_stale_entity_state_is_not_reported_as_fresh(self):
        await self.cache.remember_entity("@alice", self.entity(9))
        await asyncio.sleep(0.07)
        self.assertIsNone(await self.cache.get_entity_state("@alice", fresh=True))
        stale = await self.cache.get_entity_state("@alice", fresh=False)
        self.assertIsNotNone(stale)
        self.assertEqual(stale.entity_id, 9)

    async def test_invalidation_removes_memory_and_durable_entity(self):
        await self.cache.remember_entity("@alice", self.entity(10))
        await self.cache.invalidate_entity("@alice")
        self.assertIsNone(self.cache.get_memory_entity("@alice"))
        self.assertIsNone(await self.cache.get_entity_state("@alice"))
        row = await self.storage.fetchone("SELECT COUNT(*) FROM telegram_entities")
        self.assertEqual(int(row[0]), 0)

    async def test_dialog_cache_is_bounded_and_rebuildable(self):
        await self.cache.remember_dialog(self.dialog(1, "one"))
        await self.cache.remember_dialog(self.dialog(2, "two"))
        await self.cache.remember_dialog(self.dialog(3, "three"))

        snapshot = self.cache.snapshot()
        self.assertLessEqual(snapshot["dialogs_memory"], 2)
        row = await self.storage.fetchone("SELECT COUNT(*) FROM telegram_dialogs")
        self.assertEqual(int(row[0]), 2)

        await self.cache.close()
        rebuilt = TelegramStateCache(self.storage, dialog_ttl=60, max_dialogs=2)
        await rebuilt.start()
        states = await rebuilt.cached_dialogs()
        self.assertEqual(len(states), 2)
        self.assertEqual({state.title for state in states}, {"two", "three"})
        await rebuilt.close()

    async def test_dialog_ttl_and_invalidation(self):
        dialog = self.dialog(11, "stale")
        await self.cache.remember_dialog(dialog)
        self.assertIsNotNone(await self.cache.get_dialog_state(11))
        await asyncio.sleep(0.07)
        self.assertIsNone(await self.cache.get_dialog_state(11))
        self.assertIsNotNone(await self.cache.get_dialog_state(11, fresh=False))
        await self.cache.invalidate_dialog(11)
        self.assertIsNone(await self.cache.get_dialog_state(11, fresh=False))

    async def test_entity_memory_is_bounded(self):
        for entity_id in range(10):
            await self.cache.remember_entity(entity_id, self.entity(entity_id))
        snapshot = self.cache.snapshot()
        self.assertLessEqual(snapshot["entities_memory"], 3)
        self.assertLessEqual(snapshot["entity_states_memory"], 3)
        row = await self.storage.fetchone("SELECT COUNT(*) FROM telegram_entities")
        self.assertEqual(int(row[0]), 3)
