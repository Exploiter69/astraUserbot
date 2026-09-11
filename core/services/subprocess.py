"""Bounded, cancellable subprocess execution for shared runtime consumers."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.errors import AstraError, ErrorCode, ResourceError, TimeoutError

logger = logging.getLogger("astra.services.subprocess")


@dataclass(frozen=True, slots=True)
class SubprocessResult:
    """Safe subprocess result with bounded stdout/stderr."""

    returncode: int
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class SubprocessService:
    """Execute external programs without shell interpretation or unbounded output."""

    def __init__(self, *, default_timeout: float = 30.0, default_output_bytes: int = 1_048_576):
        if default_timeout <= 0 or default_output_bytes <= 0:
            raise ValueError("Subprocess limits must be positive")
        self.default_timeout = float(default_timeout)
        self.default_output_bytes = int(default_output_bytes)

    async def run(
        self,
        argv: Sequence[str] | str,
        *,
        timeout: float | None = None,
        max_output_bytes: int | None = None,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> SubprocessResult:
        args = self._normalize_argv(argv)
        limit = self.default_output_bytes if max_output_bytes is None else int(max_output_bytes)
        if limit <= 0:
            raise ValueError("max_output_bytes must be positive")
        timeout_value = self.default_timeout if timeout is None else float(timeout)
        if timeout_value <= 0:
            raise ValueError("timeout must be positive")

        safe_cwd = str(Path(cwd).resolve()) if cwd is not None else None
        logger.debug("Executing subprocess program=%s argc=%d cwd=%s", args[0], len(args), safe_cwd)
        process_env = None if env is None else {str(k): str(v) for k, v in env.items()}

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=safe_cwd,
                env=process_env,
            )
        except FileNotFoundError as exc:
            raise AstraError(
                "Executable not found",
                code=ErrorCode.NOT_FOUND,
                retryable=False,
            ) from exc
        except OSError as exc:
            raise AstraError(
                "Unable to start subprocess",
                code=ErrorCode.EXTERNAL_SERVICE,
                retryable=False,
            ) from exc

        stdout_task = asyncio.create_task(self._read_stream(process.stdout, limit), name="subprocess.stdout")
        stderr_task = asyncio.create_task(self._read_stream(process.stderr, limit), name="subprocess.stderr")
        try:
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout_value)
            except asyncio.TimeoutError as exc:
                await self._terminate(process)
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                raise TimeoutError(f"Subprocess timed out after {timeout_value:g}s") from exc
            except asyncio.CancelledError:
                await self._terminate(process)
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                raise

            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            return SubprocessResult(process.returncode or 0, stdout[0], stderr[0], stdout[1], stderr[1])
        finally:
            for task in (stdout_task, stderr_task):
                if not task.done():
                    task.cancel()

    @staticmethod
    def _normalize_argv(argv: Sequence[str] | str) -> list[str]:
        if isinstance(argv, str):
            argv = shlex.split(argv)
        args = [str(value) for value in argv]
        if not args or not args[0]:
            raise ValueError("Empty command")
        return args

    @staticmethod
    async def _read_stream(stream: asyncio.StreamReader | None, limit: int) -> tuple[str, bool]:
        if stream is None:
            return "", False
        chunks: list[bytes] = []
        total = 0
        truncated = False
        while True:
            chunk = await stream.read(min(65_536, limit - total + 1))
            if not chunk:
                break
            remaining = limit - total
            if remaining <= 0:
                truncated = True
                break
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                total += remaining
                truncated = True
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= limit:
                extra = await stream.read(1)
                truncated = bool(extra)
                break
        return b"".join(chunks).decode(errors="replace"), truncated

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
