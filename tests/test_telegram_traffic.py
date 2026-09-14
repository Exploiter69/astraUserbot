import asyncio
import time
import unittest

from core.errors import ResourceError
from core.services.telegram_traffic import (
    NORMAL,
    PRESSURE,
    P0_OWNER,
    P2_NORMAL,
    P5_MAINTENANCE,
    PROBE,
    THROTTLED,
    TelegramTrafficController,
)


class TelegramTrafficControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            await controller.close()

    async def test_priority_queue_prefers_owner_work(self):
        self.controller = TelegramTrafficController(max_concurrency=1)
        started = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []

        async def first():
            started.set()
            await release.wait()
            order.append("first")
            return "first"

        async def low():
            order.append("low")
            return "low"

        async def high():
            order.append("high")
            return "high"

        first_task = asyncio.create_task(
            self.controller.execute("send_message", first, priority=P2_NORMAL)
        )
        await started.wait()
        low_task = asyncio.create_task(
            self.controller.execute("send_message", low, priority=P5_MAINTENANCE)
        )
        high_task = asyncio.create_task(
            self.controller.execute("send_message", high, priority=P0_OWNER)
        )
        await asyncio.sleep(0.02)
        release.set()
        await asyncio.gather(first_task, high_task, low_task)
        self.assertEqual(order, ["first", "high", "low"])

    async def test_per_peer_limit_prevents_same_peer_overlap(self):
        self.controller = TelegramTrafficController(
            max_concurrency=4, per_peer_limit=1
        )
        first_started = asyncio.Event()
        release = asyncio.Event()
        second_started = asyncio.Event()

        async def first():
            first_started.set()
            await release.wait()
            return "first"

        async def second():
            second_started.set()
            return "second"

        first_task = asyncio.create_task(
            self.controller.execute("send_message", first, peer_key="chat:1")
        )
        await first_started.wait()
        second_task = asyncio.create_task(
            self.controller.execute("send_message", second, peer_key="chat:1")
        )
        await asyncio.sleep(0.02)
        self.assertFalse(second_started.is_set())
        release.set()
        self.assertEqual(await first_task, "first")
        self.assertEqual(await second_task, "second")
        self.assertTrue(second_started.is_set())

    async def test_flood_wait_creates_method_and_peer_cooldown(self):
        self.controller = TelegramTrafficController(max_concurrency=1)
        self.controller.record_flood_wait("send_message", 0.05, peer_key="chat:7")
        snapshot = self.controller.snapshot()
        self.assertIn("method:send_message", snapshot["cooldowns"])
        self.assertIn("peer:chat:7", snapshot["cooldowns"])

        started = time.monotonic()
        result = await self.controller.execute(
            "send_message", lambda: asyncio.sleep(0, result="ok"), peer_key="chat:7"
        )
        elapsed = time.monotonic() - started
        self.assertEqual(result, "ok")
        self.assertGreaterEqual(elapsed, 0.04)

    async def test_adaptive_governor_enters_pressure_and_reduces_concurrency(self):
        self.controller = TelegramTrafficController(max_concurrency=8)
        self.controller.record_flood_wait("send_message", 0.03, peer_key="chat:9")
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot["governor"]["account"]["state"], PRESSURE)
        self.assertEqual(snapshot["effective_concurrency"], 7)
        self.assertEqual(
            snapshot["governor"]["method:send_message"]["state"], PRESSURE
        )

    async def test_repeated_flood_wait_enters_throttled_state(self):
        self.controller = TelegramTrafficController(max_concurrency=8)
        for _ in range(2):
            self.controller.record_flood_wait("send_message", 0.05)
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot["governor"]["account"]["state"], THROTTLED)
        self.assertEqual(snapshot["effective_concurrency"], 4)

    async def test_success_after_cooldown_returns_from_probe_to_normal(self):
        self.controller = TelegramTrafficController(max_concurrency=2)
        self.controller.record_flood_wait("send_message", 0.02)
        await asyncio.sleep(0.03)
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot["governor"]["account"]["state"], PROBE)

        result = await self.controller.execute(
            "send_message", lambda: asyncio.sleep(0, result="ok")
        )
        self.assertEqual(result, "ok")
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot["governor"]["account"]["state"], NORMAL)

    async def test_queue_limit_is_bounded(self):
        self.controller = TelegramTrafficController(max_concurrency=1, max_queue=1)
        release = asyncio.Event()
        started = asyncio.Event()

        async def blocking():
            started.set()
            await release.wait()

        first = asyncio.create_task(self.controller.execute("send_message", blocking))
        await started.wait()
        queued = asyncio.create_task(
            self.controller.execute("send_message", lambda: asyncio.sleep(0))
        )
        await asyncio.sleep(0.01)
        with self.assertRaises(ResourceError):
            await self.controller.execute("send_message", lambda: asyncio.sleep(0))
        release.set()
        await asyncio.gather(first, queued)

    async def test_cancellation_stops_running_operation(self):
        self.controller = TelegramTrafficController(max_concurrency=1)
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocking():
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(self.controller.execute("send_message", blocking))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), timeout=0.5)
        await asyncio.sleep(0)
        self.assertEqual(self.controller.snapshot()["active"], 0)


if __name__ == "__main__":
    unittest.main()
