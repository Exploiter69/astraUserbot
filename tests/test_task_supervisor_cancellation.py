"""Regression tests for supervised task cancellation before first execution."""

import asyncio
import inspect

from core.tasks import TaskSupervisor


def test_cancel_before_first_turn_closes_supplied_coroutine():
    async def scenario():
        supervisor = TaskSupervisor()

        async def wait_forever():
            await asyncio.Event().wait()

        supplied = wait_forever()
        task = supervisor.create_task(supplied, name="cancel-before-first-turn")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # Task done callbacks run on the next event-loop turn.
        await asyncio.sleep(0)

        assert inspect.getcoroutinestate(supplied) == inspect.CORO_CLOSED
        assert supervisor.active() == []

    asyncio.run(scenario())
