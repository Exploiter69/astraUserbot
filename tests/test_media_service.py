import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from core.errors import CommandError, ResourceError
from core.services.media import MediaService
from core.services.subprocess import SubprocessResult, SubprocessService
from core.services.workspace import WorkspaceService


class MediaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_workspace_artifact_lifecycle_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp, max_file_bytes=32)
            service = MediaService(workspace, SubprocessService(), max_input_bytes=16, max_output_bytes=16)
            await service.start()
            job = await service.create_workspace("media")
            source = job.resolve("input.bin")
            source.write_bytes(b"1234567890")
            self.assertEqual(service.validate_input(source), source)

            output = job.resolve("output.mp4")
            output.write_bytes(b"encoded")
            artifact = service.artifact(job, "output.mp4")
            self.assertEqual(artifact.path, output)
            self.assertEqual(artifact.size_bytes, 7)
            await service.cleanup(job)
            self.assertFalse(job.path.exists())

    async def test_input_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp, max_file_bytes=128)
            service = MediaService(workspace, SubprocessService(), max_input_bytes=4)
            job = await service.create_workspace()
            source = job.resolve("input.bin")
            source.write_bytes(b"12345")
            with self.assertRaises(ResourceError):
                service.validate_input(source)
            await service.cleanup(job)

    async def test_artifact_rejects_missing_empty_and_oversized_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp, max_file_bytes=128)
            service = MediaService(workspace, SubprocessService(), max_output_bytes=4)
            job = await service.create_workspace()
            with self.assertRaises(CommandError):
                service.artifact(job, "missing.mp4")
            output = job.resolve("output.mp4")
            output.touch()
            with self.assertRaises(CommandError):
                service.artifact(job, "output.mp4")
            output.write_bytes(b"12345")
            with self.assertRaises(ResourceError):
                service.artifact(job, "output.mp4")
            await service.cleanup(job)

    async def test_run_ffmpeg_builds_explicit_argv_and_verifies_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp, max_file_bytes=128)
            service = MediaService(workspace, SubprocessService())
            job = await service.create_workspace()
            source = job.resolve("input.mp4")
            source.write_bytes(b"source")

            async def fake_run(argv, *, workspace, timeout=None, max_output_bytes=1_048_576):
                self.assertIsNotNone(workspace)
                if argv[0] == "ffmpeg":
                    self.assertEqual(argv[:5], ["ffmpeg", "-hide_banner", "-y", "-i", "/workspace/input.mp4"])
                    self.assertIn("-c:v", argv)
                    job.resolve("output.mp4").write_bytes(b"result")
                    return SubprocessResult(0, "", "")
                self.assertEqual(argv[0], "ffprobe")
                return SubprocessResult(0, "duration=12.5\nsize=6\n", "")

            service.run_isolated = AsyncMock(side_effect=fake_run)
            with patch.object(shutil, "which", return_value="/usr/bin/ffprobe"):
                _, artifact = await service.run_ffmpeg(
                    workspace=job,
                    input_path=source,
                    output_name="output.mp4",
                    options=["-c:v", "libx264"],
                )
            self.assertEqual(artifact.size_bytes, 6)
            self.assertEqual(service.run_isolated.await_count, 3)
            await service.cleanup(job)

    async def test_duration_limit_rejects_long_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            service = MediaService(workspace, SubprocessService(), max_duration_seconds=10)
            job = await service.create_workspace()
            source = job.resolve("input.mp4")
            source.write_bytes(b"source")
            service.run_isolated = AsyncMock(return_value=SubprocessResult(0, "duration=11.0\nsize=6\n", ""))
            with patch.object(shutil, "which", return_value="/usr/bin/ffprobe"):
                with self.assertRaises(ResourceError):
                    await service.verify_media(source, workspace=job)
            await service.cleanup(job)

    async def test_malformed_media_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            service = MediaService(workspace, SubprocessService())
            job = await service.create_workspace()
            source = job.resolve("broken.mp4")
            source.write_bytes(b"not-media")
            service.run_isolated = AsyncMock(return_value=SubprocessResult(1, "", "Invalid data"))
            with patch.object(shutil, "which", return_value="/usr/bin/ffprobe"):
                with self.assertRaises(CommandError):
                    await service.verify_media(source, workspace=job)
            await service.cleanup(job)

    async def test_download_discovers_only_completed_artifacts_and_verifies_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            service = MediaService(workspace, SubprocessService())
            job = await service.create_workspace()

            async def fake_run(argv, *, timeout=None, cwd=None):
                job.resolve("video.mp4").write_bytes(b"video")
                job.resolve("partial.part").write_bytes(b"partial")
                return SubprocessResult(0, "", "")

            service.subprocess.run = AsyncMock(side_effect=fake_run)
            service.verify_media = AsyncMock(return_value=None)
            _, artifacts = await service.run_download(["yt-dlp", "https://example.test"], workspace=job)
            self.assertEqual([item.path.name for item in artifacts], ["video.mp4"])
            service.verify_media.assert_awaited_once()
            await service.cleanup(job)

    async def test_concurrency_slots_bound_media_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            service = MediaService(workspace, SubprocessService(), max_concurrent_jobs=1)
            job = await service.create_workspace()
            active = 0
            peak = 0

            async def fake_run(argv, *, timeout=None, cwd=None):
                nonlocal active, peak
                self.assertIsNotNone(cwd)
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1
                return SubprocessResult(0, "", "")

            service.subprocess.run = AsyncMock(side_effect=fake_run)
            await asyncio.gather(
                service.run(["tool", "one"], workspace=job),
                service.run(["tool", "two"], workspace=job),
            )
            self.assertEqual(peak, 1)
            await service.cleanup(job)

    async def test_subprocess_cancellation_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            service = MediaService(workspace, SubprocessService())
            job = await service.create_workspace()
            started = asyncio.Event()

            async def blocking_run(argv, *, timeout=None, cwd=None):
                started.set()
                await asyncio.sleep(60)
                return SubprocessResult(0, "", "")

            service.subprocess.run = AsyncMock(side_effect=blocking_run)
            task = asyncio.create_task(service.run(["tool"], workspace=job))
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await service.cleanup(job)

    async def test_disk_exhaustion_guard_fails_before_media_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            service = MediaService(workspace, SubprocessService(), min_free_bytes=1)
            job = await service.create_workspace()
            with patch.object(shutil, "disk_usage", return_value=shutil._ntuple_diskusage(100, 99, 0)):
                with self.assertRaises(ResourceError):
                    await service.run(["tool"], workspace=job)
            await service.cleanup(job)

    async def test_rclone_policy_rejects_unsafe_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            service = MediaService(workspace, SubprocessService())
            job = await service.create_workspace()
            with self.assertRaises(CommandError):
                await service.run_rclone(["rclone", "delete", "remote:path"], workspace=job)
            service.subprocess.run = AsyncMock(return_value=SubprocessResult(0, "ok", ""))
            result = await service.run_rclone(["rclone", "copy", "/src", "remote:path"], workspace=job)
            self.assertEqual(result.returncode, 0)
            await service.cleanup(job)
