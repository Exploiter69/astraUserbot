import asyncio
import logging
import shlex
from collections.abc import Sequence

from core.errors import CommandError

logger = logging.getLogger(__name__)


async def run(argv: Sequence[str] | str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a subprocess without shell interpretation and always clean it up."""
    if isinstance(argv, str):
        argv = shlex.split(argv)
    argv = list(argv)
    if not argv:
        raise CommandError("Empty command.")

    logger.debug("Executing: %s", shlex.join(argv))
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise CommandError(f"Command not found: {argv[0]}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError as exc:
        logger.warning("Process timeout after %ss: %s", timeout, shlex.join(argv))
        await _kill(process)
        raise CommandError(f"Command timed out after {timeout}s") from exc
    except asyncio.CancelledError:
        await _kill(process)
        raise


async def _kill(process: asyncio.subprocess.Process):
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
