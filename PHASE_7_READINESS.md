# AstraUserbot — Phase 7 Media Platform Completion

**Status: COMPLETE — LOCAL REGRESSION VERIFIED**

Phase 7 made media a shared runtime platform rather than a collection of plugin-owned temporary-file and subprocess conventions.

## 1. MediaService

Created `core/services/media.py` and registered it in `ApplicationContext`.

The service owns:

- unique per-operation workspaces through `WorkspaceService`;
- bounded input/output/workspace sizes;
- bounded media duration;
- bounded concurrent media execution;
- deterministic subprocess execution through `SubprocessService`;
- explicit artifact validation and manifests;
- FFmpeg execution with explicit argv;
- FFprobe verification when available;
- TTS execution and output verification;
- deterministic download artifact discovery;
- rclone operation policy;
- free-disk protection during media execution;
- cleanup through the workspace owner.

Default policy:

```text
max input:      512 MiB
max output:     512 MiB
max workspace:  768 MiB
max duration:   2 hours
media workers:  2
FFmpeg timeout: 300s
min free disk:  128 MiB
```

## 2. All Phase 7 Consumers Migrated

The following seven consumers use `MediaService`:

```text
plugins/media/ffmpeg.py
plugins/advanced/mediaflow.py
plugins/media_ops/video.py
plugins/media_ops/speech.py
plugins/media_ops/stream.py
plugins/media/aria2.py
plugins/media/rclone.py
```

## 3. Deterministic Output Contract

Download consumers no longer select the newest file by filesystem mtime. `MediaService.run_download()` snapshots the workspace before execution and returns newly-created, verified artifacts.

FFmpeg consumers pass explicit argv arrays. User-controlled filenames are therefore not interpreted through shell quoting.

## 4. Verification

An artifact must:

- exist;
- be a regular file;
- be non-empty;
- remain within the configured output/workspace limits.

FFmpeg-produced artifacts additionally receive an FFprobe readability and duration check when `ffprobe` is available.

Downloaded audio/video/image artifacts receive the same media verification gate.

## 5. Cleanup

All seven migrated consumers allocate a unique workspace and clean it in a `finally` path. Cleanup therefore covers normal success, command failure, media failure, upload failure, and cancellation paths that unwind the handler.

## 6. Rclone Boundary

Rclone remains available, but it is no longer an unrestricted generic subprocess API. The MediaService permits only:

```text
copy
copyto
sync
```

All other rclone operations are rejected by policy.

## 7. End-to-End Hardening

The dedicated `tools/media_pipeline_audit.py` gate verifies the complete media lifecycle rather than relying only on static migration checks.

It covers:

- actual Bubblewrap-isolated FFmpeg transformation;
- input/output/workspace size limits;
- duration limits;
- malformed-media rejection;
- artifact readability verification;
- bounded media concurrency;
- subprocess cancellation propagation;
- free-disk exhaustion behavior;
- temporary workspace cleanup;
- downloader partial-file exclusion;
- shared subprocess/service boundaries across all seven consumers.

Downloads and TTS remain network-capable by design and therefore are not falsely described as isolated. FFmpeg, ffprobe, and OCR decoder workloads use the reviewed isolation boundary.

## 8. Dedicated Gate

```bash
./venv/bin/python tools/media_pipeline_audit.py
```

The actual gate requires `bwrap`, `prlimit`, `ffmpeg`, and `ffprobe`. Optional tools such as `yt-dlp`, `aria2c`, `rclone`, and `edge-tts` remain capability-gated by their individual plugins.

## 9. Regression Coverage

`tests/test_media_service.py` covers lifecycle, size enforcement, explicit FFmpeg argv, FFprobe verification, duration rejection, malformed media rejection, deterministic download artifacts, bounded concurrency, cancellation propagation, disk exhaustion handling, and rclone policy.

## 10. Completion

Phase 7 is considered fully complete only when both the normal regression suite and the dedicated media pipeline audit pass.

The original Phase 7 platform migration was already complete; this document now records the additional end-to-end production-hardening gate that closes the remaining media-pipeline work.
