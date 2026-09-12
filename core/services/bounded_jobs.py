"""Bounded lifecycle wrapper for the durable job engine.

The legacy JobEngine implementation predates the process-shutdown contract and
contains an unbounded gather during close. Production uses this wrapper so a
single cancellation-resistant handler cannot block the application lifecycle.
The durable job is marked UNCERTAIN before the service is released.
"""

from __future__ import annotations

import asyncio
import logging

from core.services.jobs import JobEngine as _JobEngine

logger = logging.getLogger("astra.jobs")


class JobEngine(_JobEngine):
    """JobEngine with a bounded, durable shutdown contract."""

    SHUTDOWN_BUDGET_SECONDS = 1.5
    WORKER_CANCEL_BUDGET_SECONDS = 0.5

    @staticmethod
    def _consume_task(task: asyncio.Task[object]) -> None:
        """Consume a late task result/exception so abandoned cleanup is quiet."""
        if not task.done():
            return
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass

    async def close(self) -> None:
        if not self._started:
            return

        started = asyncio.get_running_loop().time()
        self._stop.set()
        active_ids = list(self._active_tasks)
        active_tasks = list(self._active_tasks.values())

        for task in active_tasks:
            task.cancel()
            task.add_done_callback(self._consume_task)

        if active_tasks:
            done, pending = await asyncio.wait(
                active_tasks,
                timeout=self.SHUTDOWN_BUDGET_SECONDS,
            )
            if pending:
                logger.warning(
                    "Job shutdown budget exhausted; %d active task(s) remain cancellation-resistant",
                    len(pending),
                )

        # The durable record is authoritative even when the Python task cannot
        # be stopped. Never report active work as cleanly completed on shutdown.
        await self._mark_active_uncertain(active_ids, reason="worker_shutdown")

        worker_task = self._worker_task
        if worker_task is not None and not worker_task.done():
            worker_task.cancel()
            worker_task.add_done_callback(self._consume_task)
            try:
                await asyncio.wait_for(
                    asyncio.shield(worker_task),
                    timeout=self.WORKER_CANCEL_BUDGET_SECONDS,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("Job worker task did not stop within shutdown budget")

        self._worker_task = None
        self._active_tasks.clear()
        self._started = False
        logger.info(
            "JobEngine shutdown completed in %.3fs",
            asyncio.get_running_loop().time() - started,
        )
