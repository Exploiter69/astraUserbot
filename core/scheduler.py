"""Lifecycle-aware scheduling for process-lifetime plugin tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from core.bootstrap import supervise

logger = logging.getLogger(__name__)


def schedule_job(
    interval_seconds: int,
    coro_func: Callable[[], Awaitable[object]],
    name: str,
) -> asyncio.Task[None]:
    """Start one supervised recurring task and return its task handle.

    The caller owns the returned handle and must cancel it when the owning
    component/plugin is unloaded. The process-level supervisor remains a
    fallback for unexpected lifecycle leaks.
    """
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if not name.strip():
        raise ValueError("name is required")

    async def loop_runner() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await coro_func()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Scheduled job '%s' failed: %s", name, exc)

    return supervise(loop_runner(), name=f"scheduler_{name}")
