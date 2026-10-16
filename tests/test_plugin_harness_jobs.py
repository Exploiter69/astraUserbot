"""Integration tests for deterministic PluginHarness JobEngine driving."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from astra.testing import PluginHarness
from core.services.jobs import JobState, ReconcileOutcome


def _empty_plugins(tmp_path: Path) -> Path:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    (plugin_root / "__init__.py").touch()
    return plugin_root


def test_run_next_job_executes_registered_handler_and_persists_attempt(tmp_path: Path) -> None:
    plugin_root = _empty_plugins(tmp_path)

    async def run() -> None:
        async with PluginHarness(plugin_root=plugin_root, project_root=tmp_path) as harness:
            async def handler(job):
                return {"handled": job.payload["value"]}

            harness.jobs.register_handler("HARNESS_SUCCESS", handler)
            queued = await harness.jobs.enqueue("HARNESS_SUCCESS", {"value": 23})

            result = await harness.run_next_job()

            assert result.id == queued.id
            assert result.state == JobState.COMPLETED
            assert result.result == {"handled": 23}
            assert result.attempt_count == 1
            attempt = await harness.storage.fetchone(
                "SELECT state, finished_at FROM job_attempts WHERE job_id=? AND attempt=1",
                (queued.id,),
            )
            assert attempt["state"] == "COMPLETED"
            assert attempt["finished_at"] is not None
            events = await harness.storage.fetchall(
                "SELECT event_type FROM job_events WHERE job_id=? ORDER BY rowid",
                (queued.id,),
            )
            assert [row["event_type"] for row in events] == [
                "ENQUEUED", "CLAIMED", "COMPLETED"
            ]
            assert harness.jobs._active_tasks == {}

    asyncio.run(run())


def test_run_next_job_returns_none_without_claiming_unregistered_work(tmp_path: Path) -> None:
    plugin_root = _empty_plugins(tmp_path)

    async def run() -> None:
        async with PluginHarness(plugin_root=plugin_root, project_root=tmp_path) as harness:
            unrelated = await harness.jobs.enqueue("NOT_REGISTERED", {"keep": True})

            assert await harness.run_next_job() is None

            persisted = await harness.jobs.get(unrelated.id)
            assert persisted.state == JobState.QUEUED
            assert persisted.attempt_count == 0
            lease_count = await harness.storage.fetchone(
                "SELECT COUNT(*) AS count FROM leases WHERE job_id=?",
                (unrelated.id,),
            )
            assert lease_count["count"] == 0

    asyncio.run(run())


def test_run_next_job_refuses_when_background_worker_is_enabled(tmp_path: Path) -> None:
    plugin_root = _empty_plugins(tmp_path)

    async def run() -> None:
        async with PluginHarness(
            plugin_root=plugin_root,
            project_root=tmp_path,
            start_job_worker=True,
        ) as harness:
            assert harness.jobs._started is True
            assert harness.jobs._worker_task is not None
            with pytest.raises(RuntimeError, match="worker"):
                await harness.run_next_job()

    asyncio.run(run())


def test_run_next_job_returns_persisted_handler_failure(tmp_path: Path) -> None:
    plugin_root = _empty_plugins(tmp_path)

    async def run() -> None:
        async with PluginHarness(plugin_root=plugin_root, project_root=tmp_path) as harness:
            async def handler(_job):
                raise RuntimeError("expected handler failure")

            harness.jobs.register_handler("HARNESS_FAILURE", handler)
            queued = await harness.jobs.enqueue("HARNESS_FAILURE")

            result = await harness.run_next_job()

            assert result.id == queued.id
            assert result.state == JobState.FAILED
            assert result.error_code == "UNEXPECTED_FAILURE"
            assert result.attempt_count == 1
            assert harness.jobs._active_tasks == {}

    asyncio.run(run())


def test_run_next_job_cancellation_marks_only_still_running_job_uncertain(
    tmp_path: Path,
) -> None:
    plugin_root = _empty_plugins(tmp_path)

    async def run() -> None:
        async with PluginHarness(plugin_root=plugin_root, project_root=tmp_path) as harness:
            started = asyncio.Event()
            handler_finalized = asyncio.Event()

            async def handler(_job):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    handler_finalized.set()

            harness.jobs.register_handler("HARNESS_CANCEL", handler)
            queued = await harness.jobs.enqueue("HARNESS_CANCEL")
            driver = asyncio.create_task(harness.run_next_job())

            await asyncio.wait_for(started.wait(), timeout=1.0)
            owned_task = harness.jobs._active_tasks[queued.id]
            assert owned_task is not driver

            driver.cancel()
            with pytest.raises(asyncio.CancelledError):
                await driver

            assert handler_finalized.is_set()
            persisted = await harness.jobs.get(queued.id)
            assert persisted.state == JobState.UNCERTAIN
            assert persisted.error_code == "WORKER_SHUTDOWN"
            lease_count = await harness.storage.fetchone(
                "SELECT COUNT(*) AS count FROM leases WHERE job_id=?",
                (queued.id,),
            )
            assert lease_count["count"] == 0
            assert harness.jobs._active_tasks == {}

    asyncio.run(run())


def test_cancelled_driver_retries_transient_recovery_lookup(tmp_path: Path) -> None:
    plugin_root = _empty_plugins(tmp_path)

    async def run() -> None:
        async with PluginHarness(plugin_root=plugin_root, project_root=tmp_path) as harness:
            started = asyncio.Event()
            finished = asyncio.Event()
            real_get = harness.jobs.get
            lookup_attempts = 0

            async def handler(_job):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finished.set()

            harness.jobs.register_handler("HARNESS_CANCEL_RECOVERY_ERROR", handler)
            job = await harness.jobs.enqueue("HARNESS_CANCEL_RECOVERY_ERROR")
            driver = asyncio.create_task(harness.run_next_job())
            await asyncio.wait_for(started.wait(), timeout=1.0)

            async def flaky_get(job_id):
                nonlocal lookup_attempts
                lookup_attempts += 1
                if lookup_attempts == 1:
                    raise RuntimeError("transient recovery lookup failure")
                return await real_get(job_id)

            harness.jobs.get = flaky_get
            driver.cancel()
            with pytest.raises(asyncio.CancelledError):
                await driver

            assert finished.is_set()
            assert lookup_attempts == 2
            persisted = await real_get(job.id)
            assert persisted.state == JobState.UNCERTAIN
            assert harness.jobs._active_tasks == {}

    asyncio.run(run())


def test_real_uncertain_job_reconciliation_requeues_only_after_not_happened(
    tmp_path: Path,
) -> None:
    plugin_root = _empty_plugins(tmp_path)

    async def run() -> None:
        async with PluginHarness(plugin_root=plugin_root, project_root=tmp_path) as harness:
            observed = []

            async def handler(_job):
                return {"should_not": "run before reconciliation"}

            async def reconciler(context):
                observed.append(context)
                return ReconcileOutcome.NOT_HAPPENED

            harness.jobs.register_handler(
                "HARNESS_RECONCILE",
                handler,
                effect_class="HARNESS_TEST_EFFECT",
                reconciler=reconciler,
            )
            queued = await harness.jobs.enqueue(
                "HARNESS_RECONCILE",
                {"target": "target-17", "external_ref": "external-9"},
                idempotency_key="harness-reconcile-unique",
            )
            claimed = await harness.jobs.claim(tuple(harness.jobs.handlers))
            assert claimed is not None
            assert claimed.id == queued.id
            assert claimed.state == JobState.RUNNING
            assert claimed.attempt_count == 1

            await harness.storage.execute(
                "UPDATE leases SET expires_at=? WHERE job_id=?",
                (time.time() - 10, queued.id),
            )
            recovered = await harness.jobs.recover_expired()
            assert recovered == 1

            uncertain = await harness.jobs.get(queued.id)
            assert uncertain.state == JobState.UNCERTAIN
            assert uncertain.error_code == "LEASE_EXPIRED"

            requeued = await harness.jobs.requeue_uncertain(queued.id)
            assert requeued.state == JobState.QUEUED
            assert requeued.attempt_count == 1
            assert len(observed) == 1
            context = observed[0]
            assert context.job_id == queued.id
            assert context.job_type == "HARNESS_RECONCILE"
            assert context.effect_class == "HARNESS_TEST_EFFECT"
            assert context.attempt_number == 1
            assert context.target == "target-17"
            assert context.external_ref == "external-9"
            assert context.idempotency_key == "harness-reconcile-unique"
            assert context.attempt_started_at is not None

            effect = await harness.storage.fetchone(
                "SELECT state, reason FROM job_effects WHERE job_id=?",
                (queued.id,),
            )
            assert effect["state"] == ReconcileOutcome.NOT_HAPPENED.value
            assert effect["reason"] is None
            event_rows = await harness.storage.fetchall(
                "SELECT event_type, payload_json FROM job_events WHERE job_id=? ORDER BY rowid",
                (queued.id,),
            )
            event_types = [row["event_type"] for row in event_rows]
            assert "LEASE_EXPIRED_UNCERTAIN" in event_types
            assert "UNCERTAIN_REQUEUED" in event_types
            requeue_event = next(
                row for row in event_rows if row["event_type"] == "UNCERTAIN_REQUEUED"
            )
            assert json.loads(requeue_event["payload_json"])["state"] == "QUEUED"

            assert harness.jobs._started is False
            assert harness.jobs._worker_task is None
            assert harness.jobs._active_tasks == {}

    asyncio.run(run())
