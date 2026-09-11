import asyncio
import logging
import signal
from collections.abc import Coroutine
from typing import Any

from core.database import Database
from core.tasks import TaskSupervisor

logger = logging.getLogger(__name__)
_supervisor = TaskSupervisor()
_teardown_started = False


def supervise(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    """Compatibility wrapper for legacy callers; all tasks are centrally supervised."""
    return _supervisor.create_task(coro, name=name)


def get_task_supervisor() -> TaskSupervisor:
    """Return the process-level supervisor used by legacy bootstrap callers."""
    return _supervisor


async def shutdown(client=None):
    global _teardown_started
    if _teardown_started:
        return
    _teardown_started = True

    logger.info("Initiating graceful teardown sequence...")
    await _supervisor.shutdown(timeout=8.0)

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
