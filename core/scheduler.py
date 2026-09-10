import asyncio
import logging
from core.bootstrap import supervise

logger = logging.getLogger(__name__)

def schedule_job(interval_seconds: int, coro_func: callable, name: str):
    async def loop_runner():
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await coro_func()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduled job '{name}' failed: {e}")
                
    supervise(loop_runner(), name=f"scheduler_{name}")
