import asyncio
import tempfile
import unittest
from pathlib import Path

from core.services.jobs import JobEngine, JobError, JobState
from core.services.storage import StorageError, StorageService


class StorageAndJobsGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = StorageService(self.root)
        await self.storage.start()

    async def asyncTearDown(self):
        await self.storage.close()
        self.tmp.cleanup()

    async def test_clean_install_reaches_platform_schema(self):
        tables = await self.storage.fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        names = {row[0] for row in tables}
        self.assertTrue({'schema_migrations', 'jobs', 'job_attempts', 'job_events', 'leases', 'audit_events', 'telegram_entities', 'telegram_dialogs', 'telegram_latest_messages', 'telegram_entity_observations', 'telegram_timeline', 'telegram_replay_runs', 'intel_sources', 'intel_entities', 'intel_observations', 'intel_relationships'} <= names)
        self.assertTrue(await self.storage.integrity_check())

    async def test_migration_is_idempotent(self):
        await self.storage.close()
        await self.storage.start()
        rows = await self.storage.fetchall("SELECT version FROM schema_migrations ORDER BY version")
        self.assertEqual([row[0] for row in rows], [1, 2, 3, 4, 5, 6, 7, 8])

    async def test_foreign_keys_are_enabled(self):
        row = await self.storage.fetchone("PRAGMA foreign_keys")
        self.assertEqual(row[0], 1)

    async def test_wal_is_enabled(self):
        row = await self.storage.fetchone("PRAGMA journal_mode")
        self.assertEqual(str(row[0]).lower(), 'wal')

    async def test_migration_checksum_mismatch_is_rejected(self):
        await self.storage.execute("UPDATE schema_migrations SET checksum='bad' WHERE version=1")
        await self.storage.close()
        broken = StorageService(self.root)
        with self.assertRaises(StorageError):
            await broken.start()
        await broken.close()

    async def test_backup_round_trip(self):
        await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES ('test','x','{}',1)")
        backup = self.root / 'backup.db'
        await self.storage.backup(backup)
        self.assertTrue(backup.exists())
        import sqlite3
        conn = sqlite3.connect(backup)
        try:
            row = conn.execute("SELECT kind FROM audit_events").fetchone()
            self.assertEqual(row[0], 'test')
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            conn.close()

    async def test_enqueue_and_idempotency(self):
        engine = JobEngine(self.storage)
        first = await engine.enqueue('TEST', {'x': 1}, idempotency_key='same')
        second = await engine.enqueue('TEST', {'x': 2}, idempotency_key='same')
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.payload, {'x': 1})

    async def test_claim_and_complete(self):
        engine = JobEngine(self.storage, worker_id='gate-worker')
        job = await engine.enqueue('TEST')
        claimed = await engine.claim()
        self.assertEqual(claimed.id, job.id)
        self.assertEqual(claimed.state, JobState.RUNNING)
        self.assertEqual(claimed.attempt_count, 1)
        await engine.complete(job.id, {'ok': True})
        done = await engine.get(job.id)
        self.assertEqual(done.state, JobState.COMPLETED)
        self.assertEqual(done.result, {'ok': True})

    async def test_retry_backoff_is_bounded_by_max_attempts(self):
        engine = JobEngine(self.storage)
        job = await engine.enqueue('TEST', max_attempts=2)
        await engine.claim()
        await engine.fail(job.id, 'TEMP', 'temporary', retryable=True)
        retry = await engine.get(job.id)
        self.assertEqual(retry.state, JobState.QUEUED)
        await self.storage.execute("UPDATE jobs SET available_at=0 WHERE id=?", (job.id,))
        await engine.claim()
        await engine.fail(job.id, 'TEMP', 'temporary', retryable=True)
        failed = await engine.get(job.id)
        self.assertEqual(failed.state, JobState.FAILED)

    async def test_no_handler_fails_job_without_exposing_internal_error(self):
        engine = JobEngine(self.storage, poll_seconds=0.01)
        await engine.enqueue('UNKNOWN')
        await engine.start()
        await asyncio.sleep(0.05)
        await engine.close()
        jobs = await engine.list(limit=10)
        self.assertEqual(jobs[0].state, JobState.FAILED)
        self.assertEqual(jobs[0].error_code, 'NO_HANDLER')

    async def test_handler_success_is_durable(self):
        engine = JobEngine(self.storage, poll_seconds=0.01)
        seen = asyncio.Event()
        async def handler(job):
            seen.set()
            return {'value': job.payload['value'] + 1}
        engine.register_handler('TEST', handler)
        job = await engine.enqueue('TEST', {'value': 4})
        await engine.start()
        await asyncio.wait_for(seen.wait(), timeout=1)
        await engine.close()
        done = await engine.get(job.id)
        self.assertEqual(done.state, JobState.COMPLETED)
        self.assertEqual(done.result, {'value': 5})

    async def test_retryable_handler_error_requeues(self):
        engine = JobEngine(self.storage, poll_seconds=0.01)
        calls = 0
        ready = asyncio.Event()
        async def handler(job):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise JobError('temporary', code='TEMP', retryable=True)
            ready.set()
            return 'ok'
        engine.register_handler('TEST', handler)
        job = await engine.enqueue('TEST', max_attempts=2)
        await engine.start()
        await asyncio.wait_for(ready.wait(), timeout=2)
        await engine.close()
        done = await engine.get(job.id)
        self.assertEqual(done.state, JobState.COMPLETED)
        self.assertEqual(calls, 2)

    async def test_cancel_prevents_execution(self):
        engine = JobEngine(self.storage)
        ran = False
        async def handler(_job):
            nonlocal ran
            ran = True
        engine.register_handler('TEST', handler)
        job = await engine.enqueue('TEST')
        await engine.cancel(job.id)
        await engine.start()
        await asyncio.sleep(0.03)
        await engine.close()
        self.assertEqual((await engine.get(job.id)).state, JobState.CANCELLED)
        self.assertFalse(ran)

    async def test_expired_lease_becomes_uncertain_not_queue(self):
        engine = JobEngine(self.storage, worker_id='worker-a', lease_seconds=5)
        job = await engine.enqueue('TEST')
        await engine.claim()
        await self.storage.execute("UPDATE leases SET expires_at=0 WHERE job_id=?", (job.id,))
        recovered = await engine.recover_expired()
        self.assertEqual(recovered, 1)
        recovered_job = await engine.get(job.id)
        self.assertEqual(recovered_job.state, JobState.UNCERTAIN)
        self.assertEqual(recovered_job.error_code, 'LEASE_EXPIRED')

    async def test_uncertain_job_requires_explicit_requeue(self):
        engine = JobEngine(self.storage, worker_id='worker-a', lease_seconds=5)
        job = await engine.enqueue('TEST')
        await engine.claim()
        await self.storage.execute("UPDATE leases SET expires_at=0 WHERE job_id=?", (job.id,))
        await engine.recover_expired()
        self.assertIsNone(await engine.claim())
        requeued = await engine.requeue_uncertain(job.id)
        self.assertEqual(requeued.state, JobState.QUEUED)
        claimed = await engine.claim()
        self.assertEqual(claimed.id, job.id)

    async def test_shutdown_marks_active_job_uncertain(self):
        engine = JobEngine(self.storage, poll_seconds=0.01)
        started = asyncio.Event()
        release = asyncio.Event()
        async def handler(_job):
            started.set()
            await release.wait()
        engine.register_handler('TEST', handler)
        job = await engine.enqueue('TEST')
        await engine.start()
        await asyncio.wait_for(started.wait(), timeout=1)
        await engine.close()
        done = await engine.get(job.id)
        self.assertEqual(done.state, JobState.UNCERTAIN)
        self.assertEqual(done.error_code, 'WORKER_SHUTDOWN')

    async def test_verify_required_enters_verifying(self):
        engine = JobEngine(self.storage)
        job = await engine.enqueue('TEST', verify_required=True)
        await engine.claim()
        await engine.complete(job.id, {'candidate': True})
        self.assertEqual((await engine.get(job.id)).state, JobState.VERIFYING)
        await engine.verify(job.id, True)
        self.assertEqual((await engine.get(job.id)).state, JobState.COMPLETED)


if __name__ == '__main__':
    unittest.main()
