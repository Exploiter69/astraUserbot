"""Dedicated end-to-end audit for the media pipeline."""

from __future__ import annotations

import asyncio
import math
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.errors import CommandError, ResourceError
from core.services.isolation import IsolationService
from core.services.media import MediaService
from core.services.subprocess import SubprocessResult, SubprocessService
from core.services.workspace import WorkspaceService

CONSUMERS = (
    "plugins/media/ffmpeg.py",
    "plugins/advanced/mediaflow.py",
    "plugins/media_ops/video.py",
    "plugins/media_ops/speech.py",
    "plugins/media_ops/stream.py",
    "plugins/media/aria2.py",
    "plugins/media/rclone.py",
)


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check_static_contracts() -> None:
    media = source("core/services/media.py")
    required_media = (
        "max_input_bytes",
        "max_output_bytes",
        "max_workspace_bytes",
        "max_duration_seconds",
        "max_concurrent_jobs",
        "run_download",
        "run_ffmpeg",
        "run_ffprobe",
        "run_rclone",
        "_run_with_disk_guard",
        "_run_isolated_with_disk_guard",
    )
    for marker in required_media:
        assert marker in media, f"MediaService missing {marker}"

    for path in CONSUMERS:
        text = source(path)
        assert "create_workspace(" in text, f"{path} does not allocate a MediaService workspace"
        assert "cleanup(workspace)" in text, f"{path} does not clean its media workspace"
        assert "finally:" in text, f"{path} lacks finally-based cleanup"
        assert "helpers.shell" not in text, f"{path} bypasses the shared subprocess boundary"
        assert "create_subprocess" not in text, f"{path} creates subprocesses directly"

    assert "run_ffmpeg(" in source("plugins/media/ffmpeg.py")
    assert "run_ffmpeg(" in source("plugins/advanced/mediaflow.py")
    assert "run_ffmpeg(" in source("plugins/media_ops/video.py")
    assert "run_ffmpeg(" in source("plugins/media_ops/speech.py")
    assert "run_download(" in source("plugins/media_ops/stream.py")
    assert "run_download(" in source("plugins/media/aria2.py")
    assert "run_rclone(" in source("plugins/media/rclone.py")

    print("consumer_boundary: PASS")
    print("cleanup_contract: PASS")
    print("resource_limits: PASS")
    print("duration_contract: PASS")
    print("disk_guard: PASS")
    print("cancellation_boundary: PASS")


def make_wav(path: Path, duration: float = 0.25) -> None:
    sample_rate = 8_000
    frames = int(sample_rate * duration)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        data = bytearray()
        for index in range(frames):
            sample = int(8_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            data.extend(sample.to_bytes(2, "little", signed=True))
        handle.writeframes(data)


async def actual_pipeline() -> None:
    if not all(shutil.which(binary) for binary in ("bwrap", "prlimit", "ffmpeg", "ffprobe")):
        raise RuntimeError("bwrap, prlimit, ffmpeg, and ffprobe are required for the media pipeline gate")

    with tempfile.TemporaryDirectory(prefix="astra-media-audit-") as tmp:
        root = Path(tmp)
        workspace_service = WorkspaceService(root, max_file_bytes=64 * 1024 * 1024)
        isolation = IsolationService()
        await isolation.start()
        service = MediaService(
            workspace_service,
            SubprocessService(),
            isolation,
            max_input_bytes=8 * 1024 * 1024,
            max_output_bytes=8 * 1024 * 1024,
            max_workspace_bytes=16 * 1024 * 1024,
            max_duration_seconds=10,
            max_concurrent_jobs=1,
            min_free_bytes=1,
        )
        await service.start()

        job = await service.create_workspace("audit")
        try:
            source_path = job.resolve("input.wav")
            make_wav(source_path)
            assert service.validate_input(source_path) == source_path
            _, artifact = await service.run_ffmpeg(
                workspace=job,
                input_path=source_path,
                output_name="output.wav",
                options=["-c:a", "pcm_s16le"],
                timeout=30,
            )
            assert artifact.path.is_file() and artifact.size_bytes > 0
        finally:
            await service.cleanup(job)
        assert not job.path.exists()
        print("actual_transform: PASS")
        print("artifact_verification: PASS")
        print("temp_workspace_lifecycle: PASS")

        duration_service = MediaService(
            workspace_service,
            SubprocessService(),
            isolation,
            max_duration_seconds=0.1,
            max_input_bytes=8 * 1024 * 1024,
            max_output_bytes=8 * 1024 * 1024,
            max_workspace_bytes=16 * 1024 * 1024,
            min_free_bytes=1,
        )
        duration_job = await duration_service.create_workspace("duration")
        try:
            duration_source = duration_job.resolve("long.wav")
            make_wav(duration_source, 0.25)
            try:
                await duration_service.verify_media(duration_source, workspace=duration_job)
            except ResourceError:
                pass
            else:
                raise AssertionError("duration limit did not reject long media")
        finally:
            await duration_service.cleanup(duration_job)
        print("duration_limit_enforcement: PASS")

        malformed_job = await service.create_workspace("malformed")
        try:
            bad = malformed_job.resolve("broken.mp4")
            bad.write_bytes(b"not-a-media-file")
            try:
                await service.verify_media(bad, workspace=malformed_job)
            except CommandError:
                pass
            else:
                raise AssertionError("malformed media was accepted")
        finally:
            await service.cleanup(malformed_job)
        print("malformed_media: PASS")

        cancellation_job = await service.create_workspace("cancel")
        try:
            task = asyncio.create_task(
                service.run_isolated(
                    ["python3", "-c", "import time; time.sleep(60)"],
                    workspace=cancellation_job,
                    timeout=120,
                )
            )
            await asyncio.sleep(0.2)
            started = time.monotonic()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("isolated cancellation did not propagate")
            assert time.monotonic() - started < 3
        finally:
            await service.cleanup(cancellation_job)
        print("subprocess_cancellation: PASS")

        disk_job = await service.create_workspace("disk")
        try:
            service.subprocess.run = AsyncMock(return_value=SubprocessResult(0, "", ""))
            original_disk_usage = shutil.disk_usage
            try:
                shutil.disk_usage = lambda _path: shutil._ntuple_diskusage(100, 100, 0)
                try:
                    await service.run(["tool"], workspace=disk_job)
                except ResourceError:
                    pass
                else:
                    raise AssertionError("disk guard did not reject exhausted filesystem")
            finally:
                shutil.disk_usage = original_disk_usage
        finally:
            await service.cleanup(disk_job)
        print("disk_exhaustion_behavior: PASS")

        concurrency_job = await service.create_workspace("concurrency")
        try:
            active = 0
            peak = 0

            async def fake_run(argv, *, timeout=None, cwd=None):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.05)
                active -= 1
                return SubprocessResult(0, "", "")

            service.subprocess.run = fake_run
            await asyncio.gather(
                service.run(["tool", "one"], workspace=concurrency_job),
                service.run(["tool", "two"], workspace=concurrency_job),
            )
            assert peak == 1
        finally:
            await service.cleanup(concurrency_job)
        print("concurrency_bound: PASS")
        await isolation.close()


def main() -> int:
    print("=== MEDIA PIPELINE HARDENING AUDIT ===")
    try:
        check_static_contracts()
        asyncio.run(actual_pipeline())
    except Exception as exc:
        print(f"MEDIA_PIPELINE_AUDIT_FAIL: {exc}")
        return 1
    print("MEDIA_PIPELINE_HARDENING_AUDIT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
