"""Centralized media execution, isolation, limits, verification, and cleanup."""

from __future__ import annotations

import asyncio
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from core.errors import CommandError, ResourceError
from core.services.isolation import IsolationService
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
    DEFAULT_MIN_FREE_BYTES = 128 * 1024 * 1024
    DEFAULT_FFMPEG_THREADS = 2

    def __init__(
        self,
        workspace: WorkspaceService,
        subprocess: SubprocessService,
        isolation: IsolationService | None = None,
        *,
        max_input_bytes: int = 512 * 1024 * 1024,
        max_output_bytes: int = 512 * 1024 * 1024,
        max_workspace_bytes: int = 768 * 1024 * 1024,
        max_duration_seconds: float = 2 * 60 * 60,
        max_concurrent_jobs: int = 2,
        default_timeout: float = 300.0,
        min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    ) -> None:
        if min(max_input_bytes, max_output_bytes, max_workspace_bytes) <= 0:
            raise ValueError("Media size limits must be positive")
        if max_output_bytes > max_workspace_bytes:
            raise ValueError("max_output_bytes cannot exceed max_workspace_bytes")
        if max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be positive")
        if max_concurrent_jobs <= 0:
            raise ValueError("max_concurrent_jobs must be positive")
        if default_timeout <= 0:
            raise ValueError("default_timeout must be positive")
        if min_free_bytes < 0:
            raise ValueError("min_free_bytes cannot be negative")
        self.workspace = workspace
        self.subprocess = subprocess
        self.isolation = isolation
        self.max_input_bytes = int(max_input_bytes)
        self.max_output_bytes = int(max_output_bytes)
        self.max_workspace_bytes = int(max_workspace_bytes)
        self.max_duration_seconds = float(max_duration_seconds)
        self.default_timeout = float(default_timeout)
        self.min_free_bytes = int(min_free_bytes)
        self._slots = asyncio.Semaphore(max_concurrent_jobs)

    async def start(self) -> None:
        await self.workspace.start()

    async def close(self) -> None:
        return None

    async def create_workspace(self, name: str = "media") -> Workspace:
        await self.start()
        self._check_disk_space()
        return await self.workspace.create(name)

    async def cleanup(self, workspace: Workspace | str | Path) -> None:
        await self.workspace.cleanup(workspace)

    def _check_disk_space(self) -> None:
        usage = shutil.disk_usage(self.workspace.root)
        if usage.free < self.min_free_bytes:
            raise ResourceError("Insufficient free disk space for media work.")

    def validate_telegram_media(self, media: object) -> None:
        """Reject known-oversized Telegram media before writing it to disk."""
        file_obj = getattr(media, "file", None)
        size = getattr(media, "size", None)
        if size is None and file_obj is not None:
            size = getattr(file_obj, "size", None)
        if isinstance(size, (int, float)) and size > self.max_input_bytes:
            raise ResourceError("Telegram media exceeds the configured input size limit.")

        duration = getattr(media, "duration", None)
        if duration is None and file_obj is not None:
            duration = getattr(file_obj, "duration", None)
        if isinstance(duration, (int, float)) and duration > self.max_duration_seconds:
            raise ResourceError("Telegram media duration exceeds the configured limit.")

    def telegram_download_progress(self):
        """Return a Telethon-compatible synchronous progress guard."""
        def progress(received: int, total: int) -> None:
            if total and total > self.max_input_bytes:
                raise ResourceError("Telegram media exceeds the configured input size limit.")
            if received > self.max_input_bytes:
                raise ResourceError("Telegram media exceeded the configured input size limit during download.")

        return progress

    async def download_telegram_media(self, download_media, media: object, *, workspace: Workspace) -> str | None:
        """Download Telegram media with size, workspace, disk, and cancellation guards."""
        self.validate_telegram_media(media)
        self._check_disk_space()
        download_task = asyncio.create_task(
            download_media(
                media,
                file=workspace.path,
                progress_callback=self.telegram_download_progress(),
            ),
            name="media.telegram-download",
        )

        async def watch() -> None:
            while True:
                self._check_disk_space()
                self._validate_workspace_size(workspace)
                await asyncio.sleep(0.25)

        watch_task = asyncio.create_task(watch(), name="media.telegram-watchdog")
        try:
            done, _ = await asyncio.wait({download_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
            if watch_task in done:
                watch_task.result()
                raise ResourceError("Telegram media download stopped because storage limits were reached.")
            return download_task.result()
        except asyncio.CancelledError:
            download_task.cancel()
            await asyncio.gather(download_task, return_exceptions=True)
            raise
        finally:
            if not download_task.done():
                download_task.cancel()
                await asyncio.gather(download_task, return_exceptions=True)
            if not watch_task.done():
                watch_task.cancel()
            await asyncio.gather(watch_task, return_exceptions=True)

    def validate_input(self, path: str | Path) -> Path:
        candidate = self.workspace.validate_file(path)
        if candidate.stat().st_size > self.max_input_bytes:
            raise ResourceError("Media input exceeds the configured size limit.")
        return candidate

    def _validate_workspace_size(self, workspace: Workspace) -> None:
        total = 0
        for path in workspace.path.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError as exc:
                    raise ResourceError("Unable to inspect media workspace.") from exc
                if total > self.max_workspace_bytes:
                    raise ResourceError("Media workspace exceeds the configured size limit.")

    @staticmethod
    def _parse_probe_fields(stdout: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for line in stdout.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
        return fields

    def _validate_duration(self, duration: float | None) -> None:
        if duration is not None and duration > self.max_duration_seconds:
            raise ResourceError("Media duration exceeds the configured limit.")

    async def verify_media(self, path: str | Path, *, workspace: Workspace) -> SubprocessResult | None:
        """Verify media readability and duration when ffprobe is available."""
        if not shutil.which("ffprobe"):
            return None
        source = self.validate_input(path)
        probe = await self.run_ffprobe(source, workspace=workspace)
        if probe.returncode != 0:
            raise CommandError("Media artifact is malformed or unreadable.")
        fields = self._parse_probe_fields(probe.stdout)
        raw_duration = fields.get("duration")
        if raw_duration:
            try:
                self._validate_duration(float(raw_duration))
            except ValueError as exc:
                raise CommandError("Media duration metadata is invalid.") from exc
        return probe

    def artifact(self, workspace: Workspace, relative: str | Path) -> MediaArtifact:
        self._validate_workspace_size(workspace)
        path = workspace.resolve(relative)
        if not path.is_file():
            raise CommandError("Media operation did not produce an output file.")
        size = path.stat().st_size
        if size <= 0:
            raise CommandError("Media operation produced an empty output file.")
        if size > self.max_output_bytes:
            raise ResourceError("Media output exceeds configured size limit.")
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

    async def _run_with_disk_guard(self, argv: Sequence[str], *, workspace: Workspace, timeout: float) -> SubprocessResult:
        self._check_disk_space()
        process_task = asyncio.create_task(
            self.subprocess.run(list(argv), timeout=timeout, cwd=workspace.path),
            name="media.subprocess",
        )

        async def watch_disk() -> None:
            while True:
                self._check_disk_space()
                self._validate_workspace_size(workspace)
                await asyncio.sleep(0.25)

        disk_task = asyncio.create_task(watch_disk(), name="media.disk-watchdog")
        try:
            done, _ = await asyncio.wait({process_task, disk_task}, return_when=asyncio.FIRST_COMPLETED)
            if disk_task in done:
                disk_task.result()
                raise ResourceError("Media operation stopped because storage limits were reached.")
            return process_task.result()
        except asyncio.CancelledError:
            process_task.cancel()
            await asyncio.gather(process_task, return_exceptions=True)
            raise
        finally:
            if not process_task.done():
                process_task.cancel()
                await asyncio.gather(process_task, return_exceptions=True)
            if not disk_task.done():
                disk_task.cancel()
            await asyncio.gather(disk_task, return_exceptions=True)

    async def _run_isolated_with_disk_guard(self, argv: Sequence[str], *, workspace: Workspace, timeout: float, max_output_bytes: int) -> SubprocessResult:
        self._check_disk_space()
        isolated_task = asyncio.create_task(
            self.isolation.run(  # type: ignore[union-attr]
                list(argv),
                workspace=workspace.path,
                timeout=timeout,
                max_output_bytes=max_output_bytes,
                file_bytes=self.max_output_bytes,
            ),
            name="media.isolated-subprocess",
        )

        async def watch_disk() -> None:
            while True:
                self._check_disk_space()
                self._validate_workspace_size(workspace)
                await asyncio.sleep(0.25)

        disk_task = asyncio.create_task(watch_disk(), name="media.disk-watchdog")
        try:
            done, _ = await asyncio.wait({isolated_task, disk_task}, return_when=asyncio.FIRST_COMPLETED)
            if disk_task in done:
                disk_task.result()
                raise ResourceError("Isolated media operation stopped because storage limits were reached.")
            return isolated_task.result()
        except asyncio.CancelledError:
            isolated_task.cancel()
            await asyncio.gather(isolated_task, return_exceptions=True)
            raise
        finally:
            if not isolated_task.done():
                isolated_task.cancel()
                await asyncio.gather(isolated_task, return_exceptions=True)
            if not disk_task.done():
                disk_task.cancel()
            await asyncio.gather(disk_task, return_exceptions=True)

    async def run(self, argv: Sequence[str], *, workspace: Workspace, timeout: float | None = None) -> SubprocessResult:
        if not argv:
            raise ValueError("Media command cannot be empty")
        async with self._slots:
            result = await self._run_with_disk_guard(argv, workspace=workspace, timeout=self.default_timeout if timeout is None else timeout)
        self._validate_workspace_size(workspace)
        return result

    async def run_isolated(
        self,
        argv: Sequence[str],
        *,
        workspace: Workspace,
        timeout: float | None = None,
        max_output_bytes: int = 1_048_576,
    ) -> SubprocessResult:
        """Run a media decoder/converter inside the reviewed isolation boundary."""
        if self.isolation is None:
            raise CommandError("Isolated media execution is unavailable.")
        if not argv:
            raise ValueError("Media command cannot be empty")
        async with self._slots:
            result = await self._run_isolated_with_disk_guard(
                argv,
                workspace=workspace,
                timeout=self.default_timeout if timeout is None else timeout,
                max_output_bytes=max_output_bytes,
            )
        self._validate_workspace_size(workspace)
        return result

    async def run_download(self, argv: Sequence[str], *, workspace: Workspace, timeout: float = 600.0) -> tuple[SubprocessResult, list[MediaArtifact]]:
        before = {path for path in workspace.path.iterdir() if path.is_file()}
        result = await self.run(argv, workspace=workspace, timeout=timeout)
        if result.returncode != 0:
            detail = result.stderr[-500:] or result.stdout[-500:]
            raise CommandError(f"Download failed:\n{detail}")
        artifacts = self.discover_new_artifacts(workspace, before)
        if not artifacts:
            raise CommandError("Download completed but produced no verified artifact.")
        for artifact in artifacts:
            mime = artifact.media_type or ""
            if mime.startswith(("audio/", "video/", "image/")):
                await self.verify_media(artifact.path, workspace=workspace)
        return result, artifacts

    async def run_rclone(self, argv: Sequence[str], *, workspace: Workspace, timeout: float = 900.0) -> SubprocessResult:
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
        await self.verify_media(source, workspace=workspace)
        output = workspace.resolve(output_name)
        if output == source:
            raise ValueError("Media output must differ from input")
        input_arg = "/workspace/" + source.relative_to(workspace.path).as_posix()
        output_arg = "/workspace/" + output.relative_to(workspace.path).as_posix()
        argv = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-threads",
            str(self.DEFAULT_FFMPEG_THREADS),
            "-i",
            input_arg,
            *map(str, options),
            output_arg,
        ]
        result = await self.run_isolated(argv, workspace=workspace, timeout=timeout)
        if result.returncode != 0:
            detail = result.stderr[-500:] or result.stdout[-500:]
            raise CommandError(f"FFmpeg failed:\n{detail}")
        artifact = self.artifact(workspace, output_name)
        await self.verify_media(artifact.path, workspace=workspace)
        return result, artifact

    async def run_ffprobe(self, path: str | Path, *, workspace: Workspace, timeout: float = 30.0) -> SubprocessResult:
        source = self.validate_input(path)
        relative = source.relative_to(workspace.path).as_posix()
        return await self.run_isolated(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "default=noprint_wrappers=1", f"/workspace/{relative}"],
            workspace=workspace,
            timeout=timeout,
        )

    async def run_tts(self, *, workspace: Workspace, text: str, voice: str, output_name: str, timeout: float = 60.0) -> MediaArtifact:
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
        artifact = self.artifact(workspace, output_name)
        await self.verify_media(artifact.path, workspace=workspace)
        return artifact
