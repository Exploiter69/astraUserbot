from __future__ import annotations

import asyncio
import time
import unittest

from core.services.jobs import JobEngine, JobError, JobState
from core.services.storage import StorageService


class JobHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = StorageService(":memory:")
        await self.storage.initialize()

    async def asyncTearDown(self):
        await self.storage.close()

    async def test_idempotency_returns_existing_job(self):
        engine = JobEngine(self.storage, worker_id="idem-worker")
        first = await engine.enqueue("TEST", {"x": 1}, idempotency_key="same")
        second = await engine.enqueue("TEST", {"x": 2}, idempotency_key="same")
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.payload, {"x": 1})

    async def test_atomic_claim_prevents_duplicate_execution(self):
        first = JobEngine(self.storage, worker_id="worker-a")
        second = JobEngine(self.storage, worker_id="worker-b")
        job = await first.enqueue("TEST")
        claimed = await asyncio.gather(first.claim(), second.claim())
        self.assertEqual(sum(item is not None for item in claimed), 1)
        current = await first.get(job.id)
        self.assertEqual(current.attempt_count, 1)
        self.assertEqual(current.state, JobState.RUNNING)

    async def test_lease_fencing_rejects_stale_worker_completion(self):
        old = JobEngine(self.storage, worker_id="old-worker", lease_seconds=5)
        new = JobEngine(self.storage, worker_id="new-worker", lease_seconds=5)
        job = await old.enqueue("TEST")
        first = await old.claim()
        self.assertIsNotNone(first)
        await self.storage.execute("UPDATE leases SET expires_at=?", (time.time() - 1,))
        self.assertEqual(await new.recover_expired(), 1)
        await new.requeue_uncertain(job.id)
        second = await new.claim()
        self.assertEqual(second.attempt_count, 2)
        await old.complete(job.id, {"stale": True})
        current = await new.get(job.id)
        self.assertEqual(current.state, JobState.RUNNING)
        self.assertEqual(current.attempt_count, 2)
        self.assertIsNone(current.result)
        lease = await self.storage.fetchone("SELECT worker_id,attempt FROM leases WHERE job_id=?", (job.id,))
        self.assertEqual((lease["worker_id"], lease["attempt"]), ("new-worker", 2))

    async def test_expired_lease_becomes_uncertain(self):
        engine = JobEngine(self.storage, worker_id="expiry-worker", lease_seconds=5)
        job = await engine.enqueue("TEST")
        await engine.claim()
        await self.storage.execute("UPDATE leases SET expires_at=?", (time.time() - 1,))
        self.assertEqual(await engine.recover_expired(), 1)
        recovered = await engine.get(job.id)
        self.assertEqual(recovered.state, JobState.UNCERTAIN)
        self.assertEqual(recovered.error_code, "LEASE_EXPIRED")

    async def test_retryable_failure_requeues_then_can_succeed(self):
        engine = JobEngine(self.storage, worker_id="retry-worker", lease_seconds=5)
        job = await engine.enqueue("TEST", max_attempts=2)
        claimed = await engine.claim()
        self.assertEqual(claimed.attempt_count, 1)
        await engine.fail(job.id, "TEMP", "temporary", retryable=True)
        queued = await engine.get(job.id)
        self.assertEqual(queued.state, JobState.QUEUED)
        await self.storage.execute("UPDATE jobs SET available_at=? WHERE id=?", (time.time() - 1, job.id))
        claimed = await engine.claim()
        self.assertEqual(claimed.attempt_count, 2)
        await engine.complete(job.id, {"ok": True})
        self.assertEqual((await engine.get(job.id)).state, JobState.COMPLETED)

    async def test_retry_exhaustion_is_persistent_failure(self):
        engine = JobEngine(self.storage, worker_id="retry-exhaust-worker", lease_seconds=5)
        job = await engine.enqueue("TEST", max_attempts=1)
        await engine.claim()
        await engine.fail(job.id, "PERMANENT", "no retry", retryable=True)
        failed = await engine.get(job.id)
        self.assertEqual(failed.state, JobState.FAILED)
        self.assertEqual(failed.error_code, "PERMANENT")
        self.assertEqual(failed.error_message, "no retry")

    async def test_cancel_queued_and_active_have_distinct_semantics(self):
        engine = JobEngine(self.storage, worker_id="cancel-worker")
        queued = await engine.enqueue("TEST")
        await engine.cancel(queued.id)
        self.assertEqual((await engine.get(queued.id)).state, JobState.CANCELLED)
        active = await engine.enqueue("TEST")
        self.assertIsNotNone(await engine.claim())
        await engine.cancel(active.id)
        cancelled = await engine.get(active.id)
        self.assertEqual(cancelled.state, JobState.UNCERTAIN)
        self.assertEqual(cancelled.error_code, "CANCELLATION_UNCERTAIN")

    async def test_retention_cleanup_removes_old_terminal_jobs_but_keeps_uncertain(self):
        engine = JobEngine(self.storage, worker_id="cleanup-worker", retention_seconds=10)
        completed = await engine.enqueue("TEST")
        await engine.claim()
        await engine.complete(completed.id, {"ok": True})
        uncertain = await engine.enqueue("TEST")
        await engine.claim()
        old = time.time() - 100
        await self.storage.execute(
            "UPDATE jobs SET updated_at=?, completed_at=CASE WHEN id=? THEN ? ELSE completed_at END WHERE id IN (?,?)",
            (old, completed.id, old, completed.id, uncertain.id),
        )
        await self.storage.execute("UPDATE jobs SET state=? WHERE id=?", (JobState.UNCERTAIN.value, uncertain.id))
        result = await engine.cleanup()
        self.assertEqual(result["jobs_deleted"], 1)
        with self.assertRaises(KeyError):
            await engine.get(completed.id)
        self.assertEqual((await engine.get(uncertain.id)).state, JobState.UNCERTAIN)

    async def test_handler_success_completes_job(self):
        engine = JobEngine(self.storage, worker_id="handler-success")
        async def handler(job):
            return {"job": job.id}
        engine.register_handler("TEST", handler)
        job = await engine.enqueue("TEST")
        await engine.start()
        for _ in range(20):
            if (await engine.get(job.id)).state == JobState.COMPLETED:
                break
            await asyncio.sleep(0.01)
        await engine.close()
        self.assertEqual((await engine.get(job.id)).state, JobState.COMPLETED)

    async def test_handler_job_error_is_persistent_failure(self):
        engine = JobEngine(self.storage, worker_id="handler-error")
        async def handler(job):
            raise JobError("bad input", code="BAD_INPUT")
        engine.register_handler("TEST", handler)
        job = await engine.enqueue("TEST")
        await engine.start()
        for _ in range(20):
            if (await engine.get(job.id)).state == JobState.FAILED:
                break
            await asyncio.sleep(0.01)
        await engine.close()
        failed = await engine.get(job.id)
        self.assertEqual(failed.state, JobState.FAILED)
        self.assertEqual(failed.error_code, "BAD_INPUT")

    async def test_active_shutdown_marks_job_uncertain(self):
        engine = JobEngine(self.storage, worker_id="shutdown-worker")
        started = asyncio.Event()
        async def handler(job):
            started.set()
            await asyncio.sleep(60)
        engine.register_handler("TEST", handler)
        job = await engine.enqueue("TEST")
        await engine.start()
        await asyncio.wait_for(started.wait(), timeout=1)
        await engine.close()
        current = await engine.get(job.id)
        self.assertEqual(current.state, JobState.UNCERTAIN)
        self.assertEqual(current.error_code, "WORKER_SHUTDOWN")

    async def test_payload_and_result_bounds(self):
        engine = JobEngine(self.storage, worker_id="bounds-worker")
        with self.assertRaises(ValueError):
            await engine.enqueue("TEST", {"data": "x" * (engine.MAX_PAYLOAD_BYTES + 1)})
        job = await engine.enqueue("TEST")
        await engine.claim()
        with self.assertRaises(ValueError):
            await engine.complete(job.id, "x" * (engine.MAX_RESULT_BYTES + 1))

    async def test_verification_gate_persists_final_state(self):
        engine = JobEngine(self.storage, worker_id="verify-worker")
        job = await engine.enqueue("TEST", verify_required=True)
        await engine.claim()
        await engine.complete(job.id, {"ok": True})
        self.assertEqual((await engine.get(job.id)).state, JobState.VERIFYING)
        await engine.verify(job.id, True)
        self.assertEqual((await engine.get(job.id)).state, JobState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
