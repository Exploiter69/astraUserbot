"""Centralized media execution, isolation, limits, verification, and cleanup."""

from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from core.errors import CommandError, ResourceError
from core.services.subprocess import SubprocessResult, SubprocessService
from core.services.workspace import Workspace, WorkspaceService


@dataclass(frozen=True, slots=True)
class MediaArtifact:
    """A verified artifact owned by one media workspace."""

    path: Path
    size_bytes: int
    media_type: str | None


class MediaService:
    """Own media workspaces and deterministic external media execution."""

    def __init__(
        self,
        workspace: WorkspaceService,
        subprocess: SubprocessService,
        *,
        max_input_bytes: int = 512 * 1024 * 1024,
        max_output_bytes: int = 512 * 1024 * 1024,
        max_concurrent_jobs: int = 2,
        default_timeout: float = 300.0,
    ) -> None:
        if max_input_bytes <= 0 or max_output_bytes <= 0:
            raise ValueError("Media size limits must be positive")
        if max_concurrent_jobs <= 0:
            raise ValueError("max_concurrent_jobs must be positive")
        if default_timeout <= 0:
            raise ValueError("default_timeout must be positive")
        self.workspace = workspace
        self.subprocess = subprocess
        self.max_input_bytes = int(max_input_bytes)
        self.max_output_bytes = int(max_output_bytes)
        self.default_timeout = float(default_timeout)
        self._slots = asyncio.Semaphore(max_concurrent_jobs)

    async def start(self) -> None:
        await self.workspace.start()

    async def close(self) -> None:
        return None

    async def create_workspace(self, name: str = "media") -> Workspace:
        return await self.workspace.create(name)

    async def cleanup(self, workspace: Workspace | str | Path) -> None:
        await self.workspace.cleanup(workspace)

    def validate_input(self, path: str | Path) -> Path:
        candidate = self.workspace.validate_file(path)
        if candidate.stat().st_size > self.max_input_bytes:
            raise ResourceError("Media input exceeds the configured size limit.")
        return candidate

    def artifact(self, workspace: Workspace, relative: str | Path) -> MediaArtifact:
        path = workspace.resolve(relative)
        if not path.is_file():
            raise CommandError("Media operation did not produce an output file.")
        size = path.stat().st_size
        if size <= 0:
            raise CommandError("Media operation produced an empty output file.")
        if size > self.max_output_bytes:
            raise ResourceError("Media output exceeds the configured size limit.")
        media_type = mimetypes.guess_type(path.name)[0]
        return MediaArtifact(path=path, size_bytes=size, media_type=media_type)

    async def run(
        self,
        argv: Sequence[str],
        *,
        workspace: Workspace,
        timeout: float | None = None,
    ) -> SubprocessResult:
        if not argv:
            raise ValueError("Media command cannot be empty")
        async with self._slots:
            return await self.subprocess.run(
                list(argv),
                timeout=self.default_timeout if timeout is None else timeout,
                cwd=workspace.path,
            )

    async def run_ffmpeg(
        self,
        *,
        workspace: Workspace,
        input_path: str | Path,
        output_name: str,
        options: Sequence[str],
        timeout: float | None = None,
    ) -> tuple[SubprocessResult, MediaArtifact]:
        source = self.validate_input(input_path)
        output = workspace.resolve(output_name)
        if output == source:
            raise ValueError("Media output must differ from input")
        argv = ["ffmpeg", "-hide_banner", "-y", "-i", str(source), *map(str, options), str(output)]
        result = await self.run(argv, workspace=workspace, timeout=timeout)
        if result.returncode != 0:
            detail = result.stderr[-500:] or result.stdout[-500:]
            raise CommandError(f"FFmpeg failed:\n{detail}")
        return result, self.artifact(workspace, output_name)

    async def run_ffprobe(self, path: str | Path, *, workspace: Workspace, timeout: float = 30.0) -> SubprocessResult:
        source = self.validate_input(path)
        return await self.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "default=noprint_wrappers=1", str(source)],
            workspace=workspace,
            timeout=timeout,
        )

    async def run_tts(
        self,
        *,
        workspace: Workspace,
        text: str,
        voice: str,
        output_name: str,
        timeout: float = 60.0,
    ) -> MediaArtifact:
        if not text.strip():
            raise CommandError("TTS text cannot be empty.")
        output = workspace.resolve(output_name)
        result = await self.run(
            ["edge-tts", "--voice", voice, "--text", text, "--write-media", str(output)],
            workspace=workspace,
            timeout=timeout,
        )
        if result.returncode != 0:
            detail = result.stderr[-500:] or result.stdout[-500:]
            raise CommandError(f"TTS failed:\n{detail}")
        return self.artifact(workspace, output_name)
