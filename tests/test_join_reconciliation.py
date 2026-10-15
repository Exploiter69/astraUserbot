from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.services.jobs import JobEngine, JobError, JobState
from core.services.join_jobs import AuthoritativeJoinRejection, JOIN_JOB_TYPE, JoinJobAdapter
from core.services.storage import StorageService


class FakeTelegram:
    def __init__(self):
        self.client = self
        self.membership = "NON_MEMBER"
        self.join_request_status = "NONE"
        self.joins = []
        self.join_behavior = None
        self.membership_error = None
        self.membership_delay = 0
        self.target = "channel-1"

    async def get_entity(self, target):
        if target == "inaccessible":
            raise PermissionError("membership is restricted")
        return SimpleNamespace(id=777, target=target)

    async def get_me(self):
        return SimpleNamespace(id=42)

    async def get_membership(self, entity):
        if self.membership_error:
            raise self.membership_error
        if self.membership_delay:
            await asyncio.sleep(self.membership_delay)
        return self.membership

    async def get_join_request_status(self, entity):
        return self.join_request_status

    async def join_channel(self, target):
        self.joins.append(target)
        if self.join_behavior:
            return await self.join_behavior(target)
        self.membership = "MEMBER"
        return True


async def make_services(tmp_path: Path):
    storage = StorageService(tmp_path)
    await storage.start()
    jobs = JobEngine(storage, worker_id="join-reconcile-test", poll_seconds=0.01)
    telegram = FakeTelegram()
    adapter = JoinJobAdapter(jobs, telegram, storage)
    return storage, jobs, telegram, adapter


async def mark_uncertain(storage, job_id):
    await storage.execute(
        "UPDATE jobs SET state=?, attempt_count=1, started_at=? WHERE id=?",
        (JobState.UNCERTAIN.value, time.time() - 1, job_id),
    )


@pytest.mark.asyncio
async def test_join_happened_confirmed_membership_completes_without_rejoin(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(JOIN_JOB_TYPE, {"target": "channel-1"})
        await adapter.handle(job)
        assert telegram.joins == ["channel-1"]
        await mark_uncertain(storage, job.id)

        result = await jobs.requeue_uncertain(job.id)

        assert result.state == JobState.COMPLETED
        assert telegram.joins == ["channel-1"]
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_join_not_happened_authoritative_rejection_allows_one_retry(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(JOIN_JOB_TYPE, {"target": "channel-1"})

        async def reject(_target):
            raise AuthoritativeJoinRejection("operation definitively not accepted")

        telegram.join_behavior = reject
        claimed = await jobs.claim()
        assert claimed is not None
        with pytest.raises(JobError) as failure:
            await adapter.handle(claimed)
        assert failure.value.code == "JOIN_REJECTED"
        await jobs._fail_claimed(claimed, failure.value.code, str(failure.value), retryable=True)
        assert (await jobs.get(job.id)).state == JobState.UNCERTAIN

        telegram.membership = "NON_MEMBER"
        telegram.join_behavior = None
        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.QUEUED
        second = await jobs.claim()
        assert second is not None and second.id == job.id
        await adapter.handle(second)
        assert await jobs._complete_claimed(second, {"target": "channel-1"})
        assert (await jobs.get(job.id)).state == JobState.COMPLETED
        assert telegram.joins == ["channel-1", "channel-1"]
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "membership_not_queryable", "pending_request", "ambiguous_invite",
    "access_restricted", "timeout",
])
async def test_join_unknown_stays_uncertain_without_replay(tmp_path, case):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        target = "https://t.me/+ambiguous-invite" if case == "ambiguous_invite" else "channel-1"
        job = await jobs.enqueue(JOIN_JOB_TYPE, {"target": target})
        claimed = await jobs.claim()
        assert claimed is not None
        if case == "ambiguous_invite":
            with pytest.raises(JobError) as failure:
                await adapter.handle(claimed)
            assert failure.value.code == "JOIN_INVITE_SEMANTICS_UNKNOWN"
            await jobs._fail_claimed(claimed, failure.value.code, str(failure.value), retryable=True)
        else:
            await adapter._record_attempt(claimed, target, time.time() - 1)
            if case == "membership_not_queryable":
                telegram.membership_error = RuntimeError("lookup unavailable")
            elif case == "pending_request":
                telegram.membership = "PENDING"
                telegram.join_request_status = "PENDING"
            elif case == "access_restricted":
                target = "inaccessible"
                await storage.execute(
                    "UPDATE job_effects SET target_json=? WHERE job_id=? AND effect_class='JOIN'",
                    ('"inaccessible"', job.id),
                )
            elif case == "timeout":
                jobs.RECONCILER_TIMEOUT_SECONDS = 0.02
                telegram.membership_delay = 1
            await mark_uncertain(storage, job.id)

        result = await jobs.requeue_uncertain(job.id)
        assert result.state == JobState.UNCERTAIN
        assert telegram.joins == []
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_join_membership_miss_without_authoritative_nonapplication_stays_unknown(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(JOIN_JOB_TYPE, {"target": "channel-1"})
        claimed = await jobs.claim()
        assert claimed is not None
        await adapter._record_attempt(claimed, "channel-1", time.time() - 1)
        telegram.membership = "NON_MEMBER"
        await mark_uncertain(storage, job.id)

        result = await jobs.requeue_uncertain(job.id)

        assert result.state == JobState.UNCERTAIN
        assert telegram.joins == []
    finally:
        await jobs.close()
        await storage.close()


@pytest.mark.asyncio
async def test_join_happened_does_not_complete_other_unknown_required_effect(tmp_path):
    storage, jobs, telegram, adapter = await make_services(tmp_path)
    try:
        job = await jobs.enqueue(JOIN_JOB_TYPE, {"target": "channel-1"})
        await adapter.handle(job)
        await storage.execute(
            """INSERT INTO job_effects(effect_id,job_id,effect_class,state,required,updated_at)
               VALUES ('effect-unknown', ?, 'OTHER', 'PENDING', 1, ?)""",
            (job.id, time.time()),
        )
        await mark_uncertain(storage, job.id)

        result = await jobs.requeue_uncertain(job.id)

        assert result.state == JobState.UNCERTAIN
        rows = await storage.fetchall(
            "SELECT state FROM job_effects WHERE job_id=? AND required=1", (job.id,)
        )
        assert sorted(row["state"] for row in rows) == ["HAPPENED", "UNKNOWN"]
        assert telegram.joins == ["channel-1"]
    finally:
        await jobs.close()
        await storage.close()
