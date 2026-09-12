import asyncio
import logging
import signal
from collections.abc import Coroutine
from typing import Any, Awaitable, Callable

from core.database import Database
from core.tasks import TaskSupervisor

logger = logging.getLogger(__name__)
_supervisor = TaskSupervisor()
_teardown_started = False
LEGACY_SHUTDOWN_TIMEOUT = 2.0


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
    started = asyncio.get_running_loop().time()

    supervisor_started = asyncio.get_running_loop().time()
    await _supervisor.shutdown(timeout=LEGACY_SHUTDOWN_TIMEOUT)
    logger.info(
        "Legacy task supervisor shutdown completed in %.3fs",
        asyncio.get_running_loop().time() - supervisor_started,
    )

    database_started = asyncio.get_running_loop().time()
    await Database.close_all()
    logger.info(
        "Database shutdown completed in %.3fs",
        asyncio.get_running_loop().time() - database_started,
    )

    if client and client.is_connected():
        logger.info("Disconnecting Telegram client...")
        telegram_started = asyncio.get_running_loop().time()
        await client.disconnect()
        logger.info(
            "Telegram disconnect completed in %.3fs",
            asyncio.get_running_loop().time() - telegram_started,
        )

    logger.info(
        "Teardown complete in %.3fs",
        asyncio.get_running_loop().time() - started,
    )


# Backwards-compatible name for callers that used the old private function.
_teardown = shutdown


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    client: Any,
    shutdown_callback: Callable[[], Awaitable[Any]] | None = None,
):
    """Install SIGINT/SIGTERM handlers with an optional full-runtime callback.

    Legacy callers keep the old behavior. The production entrypoint supplies a
    callback that closes plugins and ApplicationContext before Telegram
    disconnects, so SIGTERM cannot strand runtime services behind a blocking
    client disconnect.
    """

    def request_shutdown():
        callback = shutdown_callback or (lambda: shutdown(client))
        asyncio.create_task(callback(), name="shutdown")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except (NotImplementedError, RuntimeError):
            logger.debug("Signal handler %s is unavailable on this event loop.", sig)
