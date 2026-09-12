import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from core.services.jobs import JobEngine, JobState
from core.services.storage import StorageService


class JobHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.tmp.name))
        await self.storage.start()

    async def asyncTearDown(self):
        await self.storage.close()
        self.tmp.cleanup()

    async def test_idempotency_is_durable_and_duplicate_enqueue_safe(self):
        first = await JobEngine(self.storage, worker_id="enqueue-a").enqueue("TEST", {"x": 1}, idempotency_key="same-key")
        second = await JobEngine(self.storage, worker_id="enqueue-b").enqueue("TEST", {"x": 999}, idempotency_key="same-key")
        self.assertEqual(first.id, second.id)
        rows = await self.storage.fetchall("SELECT COUNT(*) AS n FROM jobs WHERE idempotency_key=?", ("same-key",))
        self.assertEqual(rows[0]["n"], 1)

    async def test_atomic_claim_prevents_duplicate_execution(self):
        first = JobEngine(self.storage, worker_id="worker-a")
        second = JobEngine(self.storage, worker_id="worker-b")
        job = await first.enqueue("TEST")
        claimed_a, claimed_b = await asyncio.gather(first.claim(), second.claim())
        self.assertEqual(sum(item is not None for item in (claimed_a, claimed_b)), 1)
        self.assertEqual((await first.get(job.id)).attempt_count, 1)

    async def test_expired_lease_becomes_uncertain(self):
        engine = JobEngine(self.storage, worker_id="dead-worker", lease_seconds=5)
        job = await engine.enqueue("TEST")
        claimed = await engine.claim()
        self.assertIsNotNone(claimed)
        await self.storage.execute("UPDATE leases SET expires_at=? WHERE job_id=?", (time.time() - 1, job.id))
        recovered = await engine.recover_expired()
        self.assertEqual(recovered, 1)
        recovered_job = await engine.get(job.id)
        self.assertEqual(recovered_job.state, JobState.UNCERTAIN)
        self.assertEqual(recovered_job.error_code, "LEASE_EXPIRED")

    async def test_lease_fencing_rejects_stale_worker_completion(self):
        old = JobEngine(self.storage, worker_id="old-worker", lease_seconds=5)
        new = JobEngine(self.storage, worker_id="new-worker", lease_seconds=5)
        job = await old.enqueue("TEST")
        old_claim = await old.claim()
        self.assertIsNotNone(old_claim)
        await self.storage.execute("UPDATE leases SET expires_at=? WHERE job_id=?", (time.time() - 1, job.id))
        await old.recover_expired()
        await old.requeue_uncertain(job.id)
        new_claim = await new.claim()
        self.assertIsNotNone(new_claim)
        self.assertEqual(new_claim.attempt_count, 2)
        await old.complete(job.id, {"stale": True})
        current = await old.get(job.id)
        self.assertEqual(current.state, JobState.RUNNING)
        self.assertEqual(current.attempt_count, 2)
        self.assertIsNone(current.result)
        lease = await self.storage.fetchone("SELECT worker_id,attempt FROM leases WHERE job_id=?", (job.id,))
        self.assertEqual(lease["worker_id"], "new-worker")
        self.assertEqual(lease["attempt"], 2)

    async def test_retry_stops_at_max_attempts_and_persists_failure(self):
        engine = JobEngine(self.storage, worker_id="retry-worker")
        job = await engine.enqueue("TEST", max_attempts=2)
        first = await engine.claim()
        self.assertIsNotNone(first)
        self.assertTrue(await engine._fail_claimed(first, "TEMP", "temporary", retryable=True))
        retried = await engine.get(job.id)
        self.assertEqual(retried.state, JobState.QUEUED)
        self.assertEqual(retried.attempt_count, 1)
        self.assertEqual(retried.error_code, "TEMP")
        await self.storage.execute("UPDATE jobs SET available_at=? WHERE id=?", (time.time() - 1, job.id))
        second = await engine.claim()
        self.assertIsNotNone(second)
        self.assertTrue(await engine._fail_claimed(second, "PERMANENT", "final failure", retryable=True))
        failed = await engine.get(job.id)
        self.assertEqual(failed.state, JobState.FAILED)
        self.assertEqual(failed.attempt_count, 2)
        self.assertEqual(failed.error_code, "PERMANENT")
        self.assertEqual(failed.error_message, "final failure")

    async def test_cancel_queued_is_terminal_and_cancel_active_is_uncertain(self):
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
        await self.storage.execute("UPDATE jobs SET updated_at=? WHERE id IN (?,?)", (time.time() - 100, completed.id, uncertain.id))
        await self.storage.execute("UPDATE jobs SET state=? WHERE id=?", (JobState.UNCERTAIN.value, uncertain.id))
        deleted = await engine.cleanup()
        self.assertEqual(deleted, 1)
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
            await asyncio.sleep(0.05)
        self.assertEqual((await engine.get(job.id)).state, JobState.COMPLETED)
        await engine.close()

    async def test_retryable_handler_error_requeues(self):
        engine = JobEngine(self.storage, worker_id="handler-retry")
        calls = 0
        async def handler(job):
            nonlocal calls
            calls += 1
            raise RuntimeError("temporary")
        engine.register_handler("TEST", handler)
        job = await engine.enqueue("TEST", max_attempts=1)
        await engine.start()
        for _ in range(20):
            if (await engine.get(job.id)).state == JobState.FAILED:
                break
            await asyncio.sleep(0.05)
        self.assertEqual((await engine.get(job.id)).state, JobState.FAILED)
        self.assertEqual(calls, 1)
        await engine.close()

    async def test_no_handler_failure_is_persistent(self):
        engine = JobEngine(self.storage, worker_id="handler-missing")
        job = await engine.enqueue("MISSING", max_attempts=1)
        await engine.start()
        for _ in range(20):
            if (await engine.get(job.id)).state == JobState.FAILED:
                break
            await asyncio.sleep(0.05)
        failed = await engine.get(job.id)
        self.assertEqual(failed.state, JobState.FAILED)
        self.assertEqual(failed.error_code, "NO_HANDLER")
        await engine.close()

    async def test_shutdown_marks_active_job_uncertain(self):
        engine = JobEngine(self.storage, worker_id="shutdown-worker")
        started = asyncio.Event()
        async def handler(job):
            started.set()
            await asyncio.Event().wait()
        engine.register_handler("TEST", handler)
        job = await engine.enqueue("TEST")
        await engine.start()
        await asyncio.wait_for(started.wait(), timeout=2)
        await engine.close()
        self.assertEqual((await engine.get(job.id)).state, JobState.UNCERTAIN)

    async def test_verification_required_path(self):
        engine = JobEngine(self.storage, worker_id="verify-worker")
        job = await engine.enqueue("TEST", verify_required=True)
        claim = await engine.claim()
        self.assertIsNotNone(claim)
        await engine.complete(job.id, {"ok": True})
        self.assertEqual((await engine.get(job.id)).state, JobState.VERIFYING)
        await engine.verify(job.id, True)
        self.assertEqual((await engine.get(job.id)).state, JobState.COMPLETED)
