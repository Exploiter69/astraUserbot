"""Regression test for replaying uncertain external effects without reconciliation."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from core.services.jobs import JobEngine, JobState, ReconciliationRequiredError
from core.services.storage import StorageService


@pytest.mark.asyncio
async def test_uncertain_send_message_requires_reconciliation_before_requeue():
    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage, worker_id="phase1-reconcile", lease_seconds=5)
        sent_messages = []
        reconciler_calls = []
        async def reconciler_spy(job, effect_row, reconciler):
            reconciler_calls.append((job.id, effect_row["effect_id"]))
            raise AssertionError("the gate must reject before invoking a reconciler")
        engine._run_reconciler = reconciler_spy
        first_effect = asyncio.Event()

        async def send_message(job):
            sent_messages.append(job.payload["text"])
            first_effect.set()
            await asyncio.Event().wait()

        engine.register_handler("SEND_MESSAGE", send_message)
        try:
            queued = await engine.enqueue("SEND_MESSAGE", {"text": "synthetic message"})
            await engine.start()
            await asyncio.wait_for(first_effect.wait(), timeout=1.0)
            await engine.close()
            uncertain = await engine.get(queued.id)
            assert uncertain.state == JobState.UNCERTAIN

            with pytest.raises(ReconciliationRequiredError):
                await engine.requeue_uncertain(queued.id)

            unchanged = await engine.get(queued.id)
            assert unchanged.state == JobState.UNCERTAIN
            assert sent_messages == ["synthetic message"]
            assert reconciler_calls == [], "the gate must refuse before invoking observation"
        finally:
            await engine.close()
            await storage.close()


@pytest.mark.asyncio
async def test_missing_reconciler_rejection_is_generic_not_send_specific():
    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        async def fake_edit(job):
            return {"edited": True}
        engine.register_handler("FAKE_EDIT", fake_edit)
        try:
            job = await engine.enqueue("FAKE_EDIT", {"text": "synthetic"})
            await storage.execute(
                "UPDATE jobs SET state=? WHERE id=?",
                (JobState.UNCERTAIN.value, job.id),
            )
            with pytest.raises(ReconciliationRequiredError):
                await engine.requeue_uncertain(job.id)
            assert (await engine.get(job.id)).state == JobState.UNCERTAIN
        finally:
            await engine.close()
            await storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected_state"),
    [
        ("HAPPENED", JobState.COMPLETED),
        ("NOT_HAPPENED", JobState.QUEUED),
        ("UNKNOWN", JobState.UNCERTAIN),
    ],
)
async def test_fake_reconciler_outcomes_drive_engine_state(outcome, expected_state):
    from core.services.jobs import ReconcileOutcome

    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        calls = []
        async def fake_handler(job):
            return {"ran": True}
        async def fake_reconciler(context):
            calls.append(context)
            return ReconcileOutcome(outcome)
        engine.register_handler("FAKE_EFFECT", fake_handler, effect_class="FAKE", reconciler=fake_reconciler)
        try:
            job = await engine.enqueue("FAKE_EFFECT", {"value": 1})
            await storage.execute(
                "UPDATE jobs SET state=? WHERE id=?",
                (JobState.UNCERTAIN.value, job.id),
            )
            result = await engine.requeue_uncertain(job.id)
            assert result.state == expected_state
            assert len(calls) == 1
        finally:
            await engine.close()
            await storage.close()



@pytest.mark.asyncio
async def test_multi_effect_happened_plus_unknown_does_not_complete_job():
    from core.services.jobs import ReconcileOutcome

    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        async def fake_handler(job):
            return None
        async def fake_reconciler(context):
            return ReconcileOutcome.HAPPENED if context.effect_id == "effect-happened" else ReconcileOutcome.UNKNOWN
        engine.register_handler("MULTI_EFFECT", fake_handler, effect_class="FAKE", reconciler=fake_reconciler)
        try:
            job = await engine.enqueue("MULTI_EFFECT", {"target": "synthetic"})
            await storage.execute("UPDATE jobs SET state=? WHERE id=?", (JobState.UNCERTAIN.value, job.id))
            await storage.execute(
                "INSERT INTO job_effects(effect_id,job_id,effect_class,state,required,updated_at) VALUES (?,?,?,?,?,?)",
                ("effect-happened", job.id, "FAKE", "PENDING", 1, 1.0),
            )
            await storage.execute(
                "INSERT INTO job_effects(effect_id,job_id,effect_class,state,required,updated_at) VALUES (?,?,?,?,?,?)",
                ("effect-unknown", job.id, "FAKE", "PENDING", 1, 1.0),
            )
            result = await engine.requeue_uncertain(job.id)
            assert result.state == JobState.UNCERTAIN
        finally:
            await engine.close()
            await storage.close()


@pytest.mark.asyncio
async def test_retryable_failure_cannot_automatically_requeue():
    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        async def fake_handler(job):
            return None
        engine.register_handler("FAKE_RETRY", fake_handler)
        try:
            queued = await engine.enqueue("FAKE_RETRY", {})
            claimed = await engine.claim()
            assert claimed is not None and claimed.id == queued.id
            assert await engine._fail_claimed(claimed, "TRANSIENT", "uncertain effect", retryable=True)
            assert (await engine.get(queued.id)).state == JobState.UNCERTAIN
            events = await storage.fetchall("SELECT event_type,payload_json FROM job_events WHERE job_id=?", (queued.id,))
            assert any(row["event_type"] == "REPLAY_REFUSED" for row in events)
        finally:
            await engine.close()
            await storage.close()


@pytest.mark.asyncio
async def test_expired_lease_recovery_keeps_job_uncertain():
    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        async def fake_handler(job):
            return None
        engine.register_handler("FAKE_EXPIRED", fake_handler)
        try:
            queued = await engine.enqueue("FAKE_EXPIRED", {})
            claimed = await engine.claim()
            assert claimed is not None
            await storage.execute("UPDATE leases SET expires_at=0 WHERE job_id=?", (queued.id,))
            assert await engine.recover_expired() == 1
            assert (await engine.get(queued.id)).state == JobState.UNCERTAIN
            with pytest.raises(ReconciliationRequiredError):
                await engine.requeue_uncertain(queued.id)
        finally:
            await engine.close()
            await storage.close()


@pytest.mark.asyncio
async def test_cancelled_running_job_stays_uncertain_and_default_denied():
    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        async def fake_handler(job):
            return None
        engine.register_handler("FAKE_CANCEL", fake_handler)
        try:
            queued = await engine.enqueue("FAKE_CANCEL", {})
            claimed = await engine.claim()
            assert claimed is not None
            await engine.cancel(queued.id)
            assert (await engine.get(queued.id)).state == JobState.UNCERTAIN
            with pytest.raises(ReconciliationRequiredError):
                await engine.requeue_uncertain(queued.id)
        finally:
            await engine.close()
            await storage.close()


@pytest.mark.asyncio
async def test_reconciler_timeout_is_unknown_and_late_result_cannot_authorize_replay():
    from core.services.jobs import ReconcileOutcome

    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        engine.RECONCILER_TIMEOUT_SECONDS = 0.02
        started = asyncio.Event()
        release = asyncio.Event()
        async def fake_handler(job):
            return None
        async def hanging_reconciler(context):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Simulate an observer that ignores cancellation and returns late.
                await release.wait()
            return ReconcileOutcome.HAPPENED
        engine.register_handler("FAKE_TIMEOUT", fake_handler, effect_class="FAKE", reconciler=hanging_reconciler)
        try:
            uncertain = await engine.enqueue("FAKE_TIMEOUT", {})
            await storage.execute("UPDATE jobs SET state=? WHERE id=?", (JobState.UNCERTAIN.value, uncertain.id))
            other = await engine.enqueue("UNRELATED", {})
            task = asyncio.create_task(engine.requeue_uncertain(uncertain.id))
            await asyncio.wait_for(started.wait(), timeout=1)
            assert engine._reconcile_leases
            result = await asyncio.wait_for(task, timeout=0.5)
            assert result.state == JobState.UNCERTAIN
            assert not engine._reconcile_leases
            claimed = await engine.claim()
            assert claimed is not None and claimed.id == other.id
            release.set()
            await asyncio.sleep(0.03)
            assert (await engine.get(uncertain.id)).state == JobState.UNCERTAIN
            events = await storage.fetchall("SELECT payload_json FROM job_events WHERE job_id=?", (uncertain.id,))
            assert any("RECONCILER_TIMEOUT" in row["payload_json"] for row in events)
        finally:
            release.set()
            await engine.close()
            await storage.close()


@pytest.mark.asyncio
async def test_migration_does_not_infer_replay_safety_from_legacy_fields():
    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        async def legacy_handler(job):
            return None
        engine.register_handler("LEGACY_JOB", legacy_handler)
        try:
            job = await engine.enqueue("LEGACY_JOB", {}, idempotency_key="legacy-key")
            await storage.execute(
                "UPDATE jobs SET state=?,attempt_count=7 WHERE id=?",
                (JobState.UNCERTAIN.value, job.id),
            )
            await storage.close()
            reopened = StorageService(Path(tmp))
            await reopened.start()
            reopened_engine = JobEngine(reopened)
            reopened_engine.register_handler("LEGACY_JOB", legacy_handler)
            try:
                assert (await reopened_engine.get(job.id)).state == JobState.UNCERTAIN
                with pytest.raises(ReconciliationRequiredError):
                    await reopened_engine.requeue_uncertain(job.id)
                assert (await reopened_engine.get(job.id)).state == JobState.UNCERTAIN
                effects = await reopened.fetchall("SELECT * FROM job_effects WHERE job_id=?", (job.id,))
                assert effects == []
            finally:
                await reopened_engine.close()
                await reopened.close()
        finally:
            if storage.conn is not None:
                await storage.close()



@pytest.mark.asyncio
async def test_stale_reconciler_fence_cannot_authorize_replay():
    from core.services.jobs import ReconcileOutcome

    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage)
        started = asyncio.Event()
        release = asyncio.Event()
        async def fake_handler(job):
            return None
        async def stale_reconciler(context):
            started.set()
            await release.wait()
            return ReconcileOutcome.HAPPENED
        engine.register_handler("FAKE_FENCE", fake_handler, effect_class="FAKE", reconciler=stale_reconciler)
        try:
            job = await engine.enqueue("FAKE_FENCE", {})
            await storage.execute("UPDATE jobs SET state=? WHERE id=?", (JobState.UNCERTAIN.value, job.id))
            reconcile_task = asyncio.create_task(engine.requeue_uncertain(job.id))
            await asyncio.wait_for(started.wait(), timeout=1)
            effect = await storage.fetchone("SELECT effect_id,reconcile_fence FROM job_effects WHERE job_id=?", (job.id,))
            assert effect is not None
            await storage.execute(
                "UPDATE job_effects SET reconcile_token=?,reconcile_fence=reconcile_fence+1 WHERE effect_id=?",
                ("newer-owner-token", effect["effect_id"]),
            )
            release.set()
            result = await asyncio.wait_for(reconcile_task, timeout=1)
            assert result.state == JobState.UNCERTAIN
        finally:
            release.set()
            await engine.close()
            await storage.close()
