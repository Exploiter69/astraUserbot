import asyncio

import pytest

from core import bootstrap
from core.scheduler import schedule_job


@pytest.mark.asyncio
async def test_schedule_job_returns_owned_task_and_cancels_cleanly():
    bootstrap.get_task_supervisor().reset_for_testing()

    async def worker():
        return None

    task = schedule_job(3600, worker, "test_scheduler")
    assert isinstance(task, asyncio.Task)
    assert task in [record.task for record in bootstrap.get_task_supervisor().active()]

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    bootstrap.get_task_supervisor().reset_for_testing()
