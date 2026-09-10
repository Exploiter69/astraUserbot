import asyncio
import functools

# Global semaphore restricting max concurrent heavy local CPU tasks 
# Tuned specifically for a 2P+8E architecture to prevent compositor stutter.
CPU_BOUND = asyncio.Semaphore(2)
IO_BOUND = asyncio.Semaphore(10)

async def run_in_thread(func, *args, **kwargs):
    """Routes synchronous heavy functions to a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
