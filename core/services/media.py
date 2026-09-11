"""Centralized media execution, isolation, limits, verification, and cleanup."""

from __future__ import annotations

import asyncio
import mimetypes
import shutil
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

    ALLOWED_RCLONE_OPERATIONS = frozenset({"copy", "copyto", "sync"})

    def __init__(
        self,
        workspace: WorkspaceService,
        subprocess: SubprocessService,
        *,
        max_input_bytes: int = 512 * 1024 * 1024,
        max_output_bytes: int = 512 * 1024 * 1024,
        max_workspace_bytes: int = 768 * 1024 * 1024,
        max_concurrent_jobs: int = 2,
        default_timeout: float = 300.0,
    ) -> None:
        if min(max_input_bytes, max_output_bytes, max_workspace_bytes) <= 0:
            raise ValueError("Media size limits must be positive")
        if max_output_bytes > max_workspace_bytes:
            raise ValueError("max_output_bytes cannot exceed max_workspace_bytes")
        if max_concurrent_jobs <= 0:
            raise ValueError("max_concurrent_jobs must be positive")
        if default_timeout <= 0:
            raise ValueError("default_timeout must be positive")
        self.workspace = workspace
        self.subprocess = subprocess
        self.max_input_bytes = int(max_input_bytes)
        self.max_output_bytes = int(max_output_bytes)
        self.max_workspace_bytes = int(max_workspace_bytes)
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

    def _validate_workspace_size(self, workspace: Workspace) -> None:
        total = sum(path.stat().st_size for path in workspace.path.rglob("*") if path.is_file())
        if total > self.max_workspace_bytes:
            raise ResourceError("Media workspace exceeds the configured size limit.")

    def artifact(self, workspace: Workspace, relative: str | Path) -> MediaArtifact:
        self._validate_workspace_size(workspace)
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

    def discover_new_artifacts(self, workspace: Workspace, before: set[Path]) -> list[MediaArtifact]:
        self._validate_workspace_size(workspace)
        artifacts: list[MediaArtifact] = []
        for path in sorted(workspace.path.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path in before or path.name.endswith((".part", ".ytdl", ".tmp")):
                continue
            artifacts.append(self.artifact(workspace, path.name))
        return artifacts

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
            result = await self.subprocess.run(
                list(argv),
                timeout=self.default_timeout if timeout is None else timeout,
                cwd=workspace.path,
            )
        self._validate_workspace_size(workspace)
        return result

    async def run_download(
        self,
        argv: Sequence[str],
        *,
        workspace: Workspace,
        timeout: float = 600.0,
    ) -> tuple[SubprocessResult, list[MediaArtifact]]:
        before = {path for path in workspace.path.iterdir() if path.is_file()}
        result = await self.run(argv, workspace=workspace, timeout=timeout)
        if result.returncode != 0:
            detail = result.stderr[-500:] or result.stdout[-500:]
            raise CommandError(f"Download failed:\n{detail}")
        artifacts = self.discover_new_artifacts(workspace, before)
        if not artifacts:
            raise CommandError("Download completed but produced no verified artifact.")
        return result, artifacts

    async def run_rclone(
        self,
        argv: Sequence[str],
        *,
        workspace: Workspace,
        timeout: float = 900.0,
    ) -> SubprocessResult:
        if len(argv) < 2 or argv[0] != "rclone":
            raise ValueError("Rclone command must begin with rclone")
        operation = argv[1].lower()
        if operation not in self.ALLOWED_RCLONE_OPERATIONS:
            raise CommandError(f"Rclone operation '{operation}' is not allowed by media policy.")
        return await self.run(argv, workspace=workspace, timeout=timeout)

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
        artifact = self.artifact(workspace, output_name)
        if shutil.which("ffprobe"):
            probe = await self.run_ffprobe(artifact.path, workspace=workspace)
            if probe.returncode != 0:
                raise CommandError("FFmpeg produced an unreadable media artifact.")
        return result, artifact

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
