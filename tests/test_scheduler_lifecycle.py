import asyncio

import pytest

from core import bootstrap
from core.scheduler import schedule_job


@pytest.mark.asyncio
async def test_schedule_job_returns_owned_task_and_cancels_cleanly(monkeypatch):
    bootstrap.get_task_supervisor().reset_for_testing()
    ticks = 0

    async def worker():
        nonlocal ticks
        ticks += 1

    task = schedule_job(3600, worker, "test_scheduler")
    try:
        assert isinstance(task, asyncio.Task)
        assert task in [record.task for record in bootstrap.get_task_supervisor().active()]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        bootstrap.get_task_supervisor().reset_for_testing()


@pytest.mark.asyncio
async def test_legacy_supervisor_shutdown_is_bounded():
    bootstrap.get_task_supervisor().reset_for_testing()

    async def stubborn():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            while True:
                await asyncio.sleep(0)

    bootstrap.get_task_supervisor().create_task(stubborn(), name="stubborn_scheduler")
    started = asyncio.get_running_loop().time()
    await bootstrap.get_task_supervisor().shutdown(timeout=0.05)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.5
    bootstrap.get_task_supervisor().reset_for_testing()
