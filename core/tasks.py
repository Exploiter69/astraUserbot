"""Supervision for ephemeral long-lived asyncio tasks."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable

from core.errors import ErrorCode, as_astra_error

logger = logging.getLogger("astra.tasks")


class TaskState(StrEnum):
    """Observable lifecycle states for supervised tasks."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class TaskRecord:
    """Bounded diagnostic metadata for one supervised task."""

    task_id: str
    name: str
    owner: str | None
    created_at: float
    state: TaskState
    task: asyncio.Task[Any]
    finished_at: float | None = None
    error_code: ErrorCode | None = None

    @property
    def done(self) -> bool:
        return self.task.done()


class TaskSupervisor:
    """Own and supervise process-lifetime asyncio tasks.

    This is intentionally ephemeral: it never claims restart durability. Work
    that must survive process loss belongs to the durable Job Engine.
    """

    def __init__(self, *, history_limit: int = 256) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self.history_limit = history_limit
        self._active: dict[str, TaskRecord] = {}
        self._history: deque[TaskRecord] = deque(maxlen=history_limit)
        self._shutting_down = False

    def create_task(
        self,
        awaitable: Awaitable[Any],
        *,
        name: str,
        owner: str | None = None,
    ) -> asyncio.Task[Any]:
        """Create and register one supervised task."""
        if self._shutting_down:
            close = getattr(awaitable, "close", None)
            if close is not None:
                close()
            raise RuntimeError("TaskSupervisor is shutting down")
        if not name.strip():
            close = getattr(awaitable, "close", None)
            if close is not None:
                close()
            raise ValueError("task name is required")

        task = asyncio.create_task(awaitable, name=name)
        record = TaskRecord(
            task_id=uuid.uuid4().hex[:12],
            name=name,
            owner=owner,
            created_at=time.time(),
            state=TaskState.RUNNING,
            task=task,
        )
        self._active[record.task_id] = record
        task.add_done_callback(lambda finished: self._finish(record, finished))
        return task

    def _finish(self, record: TaskRecord, task: asyncio.Task[Any]) -> None:
        record.finished_at = time.time()
        try:
            task.result()
        except asyncio.CancelledError:
            record.state = TaskState.CANCELLED
            return self._archive(record)
        except Exception as exc:
            error = as_astra_error(
                exc,
                operation=record.name,
                component="task_supervisor",
                correlation_id=record.task_id,
            )
            record.state = TaskState.FAILED
            record.error_code = error.code
            logger.error(
                "Supervised task failed id=%s name=%s owner=%s code=%s",
                record.task_id,
                record.name,
                record.owner or "unknown",
                error.code,
                exc_info=True,
            )
            return self._archive(record)
        record.state = TaskState.COMPLETED
        self._archive(record)

    def _archive(self, record: TaskRecord) -> None:
        self._active.pop(record.task_id, None)
        self._history.append(record)

    def get(self, task_id: str) -> TaskRecord | None:
        return self._active.get(task_id) or next(
            (item for item in reversed(self._history) if item.task_id == task_id),
            None,
        )

    def active(self) -> list[TaskRecord]:
        return sorted(self._active.values(), key=lambda item: item.created_at)

    def history(self) -> list[TaskRecord]:
        return list(self._history)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return safe, bounded diagnostics without exposing task objects."""
        records = [*self._history, *self._active.values()]
        return [
            {
                "task_id": record.task_id,
                "name": record.name,
                "owner": record.owner,
                "created_at": record.created_at,
                "finished_at": record.finished_at,
                "state": record.state.value,
                "error_code": record.error_code.value if record.error_code else None,
            }
            for record in sorted(records, key=lambda item: item.created_at)
        ]

    async def cancel(self, task_id: str) -> bool:
        """Cancel one active task and wait for cancellation to settle."""
        record = self._active.get(task_id)
        if record is None or record.task.done():
            return False
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)
        return True

    async def shutdown(self, *, timeout: float = 1.0) -> None:
        """Stop active tasks without allowing shutdown to hang indefinitely.

        The timeout bounds the graceful wait.  Tasks that remain active after
        that deadline are cancelled and given one event-loop turn to process
        cancellation.  A Python coroutine cannot be forcibly terminated from
        its owning event loop, so cancellation-resistant tasks may remain
        pending; shutdown deliberately returns rather than waiting forever.
        """
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        self._shutting_down = True
        current = asyncio.current_task()
        tasks = [
            record.task
            for record in self._active.values()
            if record.task is not current and not record.task.done()
        ]
        if not tasks:
            return

        _, pending = await asyncio.wait(tasks, timeout=timeout)
        if not pending:
            return

        for task in pending:
            task.cancel()

        # Cancellation is cooperative.  Give callbacks/finalizers one event
        # loop turn, but never await a cancellation-resistant coroutine.
        await asyncio.sleep(0)
        still_pending = [task for task in pending if not task.done()]
        if still_pending:
            logger.warning(
                "TaskSupervisor shutdown timed out with %d task(s) still pending",
                len(still_pending),
            )

    def reset_for_testing(self) -> None:
        """Clear supervisor state for isolated unit tests."""
        self._active.clear()
        self._history.clear()
        self._shutting_down = False
