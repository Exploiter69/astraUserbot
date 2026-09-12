import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from core.services.bounded_jobs import JobEngine
from core.services.jobs import JobState
from core.services.storage import StorageService


class BoundedJobShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tmp.name))
        await self.storage.start()

    async def asyncTearDown(self):
        await self.storage.close()
        self.tmp.cleanup()

    async def test_cancellation_resistant_handler_cannot_block_close(self):
        engine = JobEngine(self.storage, poll_seconds=0.01)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def stubborn(_job):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        engine.register_handler("STUBBORN", stubborn)
        job = await engine.enqueue("STUBBORN")
        await engine.start()
        await asyncio.wait_for(entered.wait(), timeout=1)
        task = engine._active_tasks[job.id]

        started = time.monotonic()
        await engine.close()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, JobEngine.SHUTDOWN_BUDGET_SECONDS + JobEngine.WORKER_CANCEL_BUDGET_SECONDS + 0.5)
        self.assertEqual((await engine.get(job.id)).state, JobState.UNCERTAIN)
        self.assertEqual((await engine.get(job.id)).error_code, "WORKER_SHUTDOWN")

        release.set()
        await asyncio.wait_for(task, timeout=1)


if __name__ == "__main__":
    unittest.main()
