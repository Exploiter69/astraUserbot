"""Durable job payload/result resource-boundary tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.services.jobs import JobEngine
from core.services.storage import StorageService


class JobResourceBoundsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tmp.name))
        await self.storage.start()
        self.engine = JobEngine(self.storage)

    async def asyncTearDown(self):
        await self.storage.close()
        self.tmp.cleanup()

    async def test_payload_is_bounded(self):
        with self.assertRaises(ValueError):
            await self.engine.enqueue("TEST", {"data": "x" * self.engine.MAX_PAYLOAD_BYTES})

    async def test_result_is_bounded(self):
        job = await self.engine.enqueue("TEST")
        await self.engine.claim()
        with self.assertRaises(ValueError):
            await self.engine.complete(job.id, {"data": "x" * self.engine.MAX_RESULT_BYTES})

    async def test_job_metadata_is_bounded(self):
        with self.assertRaises(ValueError):
            await self.engine.enqueue("x" * (self.engine.MAX_JOB_TYPE_CHARS + 1))
        with self.assertRaises(ValueError):
            await self.engine.enqueue("TEST", owner="x" * (self.engine.MAX_OWNER_CHARS + 1))
        with self.assertRaises(ValueError):
            await self.engine.enqueue("TEST", resource_class="x" * (self.engine.MAX_RESOURCE_CLASS_CHARS + 1))
        with self.assertRaises(ValueError):
            await self.engine.enqueue("TEST", idempotency_key="x" * (self.engine.MAX_IDEMPOTENCY_KEY_CHARS + 1))


if __name__ == "__main__":
    unittest.main()
