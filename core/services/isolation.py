"""Explicit process isolation for untrusted or high-risk workloads."""

from __future__ import annotations

import asyncio
import os
import resource
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from core.errors import ExternalServiceError, TimeoutError
from core.services.subprocess import SubprocessResult


@dataclass(frozen=True, slots=True)
class IsolationAssessment:
    enabled: bool
    backend: str
    reason: str


class IsolationUnavailable(RuntimeError):
    """Raised when a workload explicitly requires an unavailable backend."""


class IsolationService:
    """Provide explicit, measured Bubblewrap isolation for child processes.

    Ordinary plugins remain same-process and are never described as sandboxed.
    Callers must explicitly request ``run`` for an isolated workload.
    """

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_OUTPUT_BYTES = 1_048_576
    DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
    DEFAULT_FILE_BYTES = 8 * 1024 * 1024
    DEFAULT_PROCESSES = 16
    DEFAULT_NOFILE = 64

    def __init__(self) -> None:
        self._started = False
        self._backend = "none"
        self._reason = "No isolation backend enabled; plugins remain same-process and therefore same-trust."
        self._bwrap: str | None = None

    async def start(self) -> None:
        self._bwrap = shutil.which("bwrap")
        if self._bwrap:
            self._backend = "bubblewrap-available"
            self._reason = "Bubblewrap is available for explicitly isolated child workloads; ordinary plugins remain same-process."
        elif shutil.which("firejail"):
            self._backend = "firejail-available"
            self._reason = "Firejail is detected but is not used by the reviewed isolation executor."
        self._started = True

    async def close(self) -> None:
        self._started = False

    def assess(self) -> IsolationAssessment:
        return IsolationAssessment(bool(self._bwrap), self._backend, self._reason)

    def require_explicit_backend(self) -> None:
        if not self._bwrap:
            raise IsolationUnavailable("Bubblewrap is required for this isolated workload but is unavailable.")

    @staticmethod
    def _child_limits(memory_bytes: int, file_bytes: int, processes: int, nofile: int) -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC, (processes, processes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        return {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/tmp",
            "LANG": "C",
            "LC_ALL": "C",
            "TMPDIR": "/tmp",
        }

    @staticmethod
    def _bind_ro_args() -> list[str]:
        args = ["--ro-bind", "/usr", "/usr"]
        if os.path.exists("/etc"):
            args.extend(["--ro-bind", "/etc", "/etc"])
        for link, target in (("/bin", "usr/bin"), ("/sbin", "usr/sbin"), ("/lib", "usr/lib"), ("/lib64", "usr/lib64")):
            if os.path.islink(link) and os.path.exists(link):
                args.extend(["--symlink", target, link])
        return args

    async def run(
        self,
        argv: Sequence[str],
        *,
        workspace: str | Path,
        timeout: float = DEFAULT_TIMEOUT,
        max_output_bytes: int = DEFAULT_OUTPUT_BYTES,
        memory_bytes: int = DEFAULT_MEMORY_BYTES,
        file_bytes: int = DEFAULT_FILE_BYTES,
        processes: int = DEFAULT_PROCESSES,
        nofile: int = DEFAULT_NOFILE,
    ) -> SubprocessResult:
        self.require_explicit_backend()
        args = [str(item) for item in argv]
        if not args or not args[0]:
            raise ValueError("Isolated command cannot be empty")
        if timeout <= 0 or max_output_bytes <= 0:
            raise ValueError("Isolation limits must be positive")
        if min(memory_bytes, file_bytes, processes, nofile) <= 0:
            raise ValueError("Isolation resource limits must be positive")

        root = Path(workspace).resolve()
        if not root.is_dir():
            raise ValueError("Isolation workspace must be an existing directory")

        command = [
            self._bwrap or "bwrap",
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--unshare-user",
            "--disable-userns",
            "--cap-drop", "ALL",
            "--clearenv",
            *self._bind_ro_args(),
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--bind", str(root), "/workspace",
            "--chdir", "/workspace",
            "--setenv", "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "--setenv", "HOME", "/tmp",
            "--setenv", "LANG", "C",
            "--setenv", "LC_ALL", "C",
            "--setenv", "TMPDIR", "/tmp",
            "--",
            *args,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(root),
                env=self._minimal_environment(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=lambda: self._child_limits(memory_bytes, file_bytes, processes, nofile),
            )
        except OSError as exc:
            raise ExternalServiceError("Unable to start isolated subprocess") from exc

        async def read_bounded(stream: asyncio.StreamReader | None) -> tuple[str, bool]:
            if stream is None:
                return "", False
            chunks: list[bytes] = []
            total = 0
            truncated = False
            while True:
                chunk = await stream.read(65_536)
                if not chunk:
                    break
                remaining = max_output_bytes - total
                if remaining > 0:
                    chunks.append(chunk[:remaining])
                    total += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    truncated = True
            return b"".join(chunks).decode(errors="replace"), truncated

        stdout_task = asyncio.create_task(read_bounded(process.stdout))
        stderr_task = asyncio.create_task(read_bounded(process.stderr))
        try:
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.wait()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                raise TimeoutError(f"Isolated subprocess timed out after {timeout:g}s") from exc
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                raise
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            return SubprocessResult(
                process.returncode or 0,
                stdout[0],
                stderr[0],
                stdout[1],
                stderr[1],
            )
        finally:
            for task in (stdout_task, stderr_task):
                if not task.done():
                    task.cancel()
