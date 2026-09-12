from __future__ import annotations

import asyncio
import unittest

from core import bootstrap


class FakeLoop:
    def __init__(self):
        self.handlers = {}

    def add_signal_handler(self, sig, callback):
        self.handlers[sig] = callback


class ShutdownRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_custom_shutdown_callback_is_scheduled(self):
        loop = FakeLoop()
        called = asyncio.Event()

        async def callback():
            called.set()

        bootstrap.install_signal_handlers(loop, object(), callback)
        self.assertEqual(2, len(loop.handlers))

        loop.handlers[next(iter(loop.handlers))]()
        await asyncio.wait_for(called.wait(), timeout=1)
        remaining = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in remaining:
            if not task.done():
                task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)

    async def test_legacy_shutdown_path_remains_the_default(self):
        loop = FakeLoop()
        bootstrap.install_signal_handlers(loop, object())
        self.assertEqual(2, len(loop.handlers))


if __name__ == "__main__":
    unittest.main()
