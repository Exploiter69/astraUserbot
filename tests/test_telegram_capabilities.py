import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.services.storage import StorageService
from core.services.telegram import TelegramFacade
from core.services.telegram_state import TelegramStateCache


class TelegramCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tempdir.name))
        await self.storage.start()
        self.cache = TelegramStateCache(self.storage, entity_ttl=0.05)
        await self.cache.start()

    async def asyncTearDown(self) -> None:
        await self.cache.close()
        await self.storage.close()
        self.tempdir.cleanup()

    @staticmethod
    def entity(entity_id: int = 42):
        return SimpleNamespace(
            id=entity_id,
            access_hash=entity_id * 10,
            username="example",
            first_name="Example",
            last_name=None,
            title="Example Group",
            photo=None,
            slowmode_seconds=30,
            restricted=False,
        )

    async def test_capabilities_are_observed_and_persisted(self):
        class Client:
            def __init__(self):
                self.entity_calls = 0
                self.permission_calls = 0

            async def get_entity(self, _lookup):
                self.entity_calls += 1
                return TelegramCapabilityTests.entity()

            async def get_permissions(self, _entity, _who):
                self.permission_calls += 1
                return SimpleNamespace(
                    send_messages=True,
                    edit_messages=False,
                    delete_messages=True,
                    pin_messages=False,
                    send_reactions=True,
                )

        client = Client()
        facade = TelegramFacade(client, retries=0, state_cache=self.cache)
        capabilities = await facade.get_capabilities("@example")
        await facade.close()

        self.assertTrue(capabilities["can_read"])
        self.assertTrue(capabilities["can_send"])
        self.assertFalse(capabilities["can_edit"])
        self.assertTrue(capabilities["can_delete"])
        self.assertFalse(capabilities["can_pin"])
        self.assertTrue(capabilities["can_react"])
        self.assertEqual(capabilities["slow_mode_seconds"], 30)
        self.assertFalse(capabilities["restricted"])
        self.assertEqual(client.entity_calls, 1)
        self.assertEqual(client.permission_calls, 1)

        state = await self.cache.get_entity_state("@example")
        self.assertIsNotNone(state)
        self.assertEqual(state.capabilities["can_send"], True)
        self.assertIn("observed_at", state.capabilities)

    async def test_fresh_capability_cache_avoids_second_telegram_permission_call(self):
        class Client:
            def __init__(self):
                self.entity_calls = 0
                self.permission_calls = 0
                self.entity = TelegramCapabilityTests.entity(7)

            async def get_entity(self, _lookup):
                self.entity_calls += 1
                return self.entity

            async def get_permissions(self, _entity, _who):
                self.permission_calls += 1
                return SimpleNamespace(send_messages=True)

        client = Client()
        facade = TelegramFacade(client, retries=0, state_cache=self.cache)
        first = await facade.get_capabilities("@example")
        second = await facade.get_capabilities("@example")
        await facade.close()

        self.assertEqual(first["can_send"], True)
        self.assertEqual(second["can_send"], True)
        self.assertEqual(client.entity_calls, 1)
        self.assertEqual(client.permission_calls, 1)

    async def test_stale_capabilities_are_reobserved(self):
        class Client:
            def __init__(self):
                self.permission_calls = 0
                self.entity = TelegramCapabilityTests.entity(8)

            async def get_entity(self, _lookup):
                return self.entity

            async def get_permissions(self, _entity, _who):
                self.permission_calls += 1
                return SimpleNamespace(send_messages=self.permission_calls == 1)

        client = Client()
        facade = TelegramFacade(client, retries=0, state_cache=self.cache)
        first = await facade.get_capabilities("@example")
        self.assertTrue(first["can_send"])
        await asyncio.sleep(0.07)
        second = await facade.get_capabilities("@example")
        await facade.close()

        self.assertFalse(second["can_send"])
        self.assertEqual(client.permission_calls, 2)

    async def test_permission_failure_is_an_observation_not_a_facade_failure(self):
        class Client:
            async def get_entity(self, _lookup):
                return TelegramCapabilityTests.entity(9)

            async def get_permissions(self, _entity, _who):
                raise RuntimeError("permissions unavailable")

        facade = TelegramFacade(Client(), retries=0, state_cache=self.cache)
        capabilities = await facade.get_capabilities("@example")
        await facade.close()

        self.assertTrue(capabilities["can_read"])
        self.assertIsNone(capabilities["can_send"])
        self.assertEqual(capabilities["permissions_observation"], "UNAVAILABLE")
        self.assertEqual(capabilities["permissions_error"], "RuntimeError")
