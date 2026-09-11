import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock

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

            async def fake_run(argv, *, workspace, timeout=None):
                if argv[0] == "ffmpeg":
                    self.assertEqual(argv[:5], ["ffmpeg", "-hide_banner", "-y", "-i", str(source)])
                    self.assertIn("-c:v", argv)
                    job.resolve("output.mp4").write_bytes(b"result")
                else:
                    self.assertEqual(argv[0], "ffprobe")
                return SubprocessResult(0, "", "")

            service.run = AsyncMock(side_effect=fake_run)
            _, artifact = await service.run_ffmpeg(
                workspace=job,
                input_path=source,
                output_name="output.mp4",
                options=["-c:v", "libx264"],
            )
            self.assertEqual(artifact.size_bytes, 6)
            self.assertEqual(service.run.await_count, 2)
            await service.cleanup(job)

    async def test_concurrency_slots_bound_media_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            service = MediaService(workspace, SubprocessService(), max_concurrent_jobs=1)
            job = await service.create_workspace()
            active = 0
            peak = 0

            async def fake_run(argv, *, workspace, timeout=None):
                nonlocal active, peak
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
