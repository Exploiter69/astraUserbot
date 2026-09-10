import asyncio
import functools
import logging
import signal
from collections.abc import Coroutine
from typing import Any

from core.database import Database

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task] = set()
_teardown_started = False


def _log_task_result(task: asyncio.Task, name: str):
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Background task '%s' failed: %s", name, exc, exc_info=True)


def supervise(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(functools.partial(_log_task_result, name=name))
    return task


async def shutdown(client=None):
    global _teardown_started
    if _teardown_started:
        return
    _teardown_started = True

    logger.info("Initiating graceful teardown sequence...")

    current = asyncio.current_task()
    pending_tasks = {
        task for task in _background_tasks
        if task is not current and not task.done()
    }
    if pending_tasks:
        logger.info("Waiting for %d background tasks...", len(pending_tasks))
        _, pending = await asyncio.wait(pending_tasks, timeout=8.0)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    await Database.close_all()

    if client and client.is_connected():
        logger.info("Disconnecting Telegram client...")
        await client.disconnect()

    logger.info("Teardown complete.")


# Backwards-compatible name for callers that used the old private function.
_teardown = shutdown


def install_signal_handlers(loop: asyncio.AbstractEventLoop, client):
    def request_shutdown():
        asyncio.create_task(shutdown(client), name="shutdown")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except (NotImplementedError, RuntimeError):
            logger.debug("Signal handler %s is unavailable on this event loop.", sig)
