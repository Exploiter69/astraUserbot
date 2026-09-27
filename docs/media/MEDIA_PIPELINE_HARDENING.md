# AstraUserbot — Media Pipeline Hardening

## Status

**Complete after the dedicated end-to-end media pipeline gate passes.**

The media path is treated as a bounded operation with a unique workspace, explicit subprocess argv, isolated decoding/conversion where required, artifact verification, bounded concurrency, cancellation propagation, and deterministic cleanup.

## Pipeline

```text
Telegram
   ↓
MediaService workspace
   ↓
download / input validation
   ↓
FFmpeg / ffprobe / external tool
   ↓
artifact verification
   ↓
Telegram upload / remote copy
   ↓
workspace cleanup
```

## Enforced limits

| Boundary | Default |
|---|---:|
| Input file | 512 MiB |
| Output artifact | 512 MiB |
| Workspace | 768 MiB |
| Media duration | 2 hours |
| Concurrent media operations | 2 |
| Default media execution timeout | 300 seconds |
| Minimum free disk guard | 128 MiB |

The audit may use smaller limits to exercise rejection paths.

## Download safety

`MediaService.run_download()` snapshots the workspace before execution and accepts only newly-created regular files. Temporary downloader artifacts such as `.part`, `.ytdl`, and `.tmp` are excluded.

Completed audio/video/image artifacts are passed through `ffprobe` when available. Unreadable media is rejected and duration is checked against the configured maximum.

Downloads are still intentionally non-isolated because network access is required. They use the shared `SubprocessService` and are bounded by timeout, output limits, workspace limits, and the disk guard.

## Transformation safety

FFmpeg and ffprobe execution goes through the explicit Bubblewrap isolation boundary. User-controlled paths are converted into `/workspace/...` arguments and commands are passed as argv arrays; shell interpretation is not used.

Input media is probed before transformation. The produced artifact is checked for existence, regular-file status, non-zero size, output/workspace bounds, readability, and duration.

## Malformed media

Malformed media is rejected by the ffprobe readability gate instead of being treated as a successful artifact merely because a file exists.

## Duration safety

Media duration is read from ffprobe's `format=duration` output. A duration above the configured bound is rejected before transformation or upload. Missing duration metadata is tolerated for formats where ffprobe cannot report it, while malformed duration metadata is rejected.

## Cancellation

Cancellation propagates through `MediaService` to the underlying subprocess task. The shared subprocess/isolation services terminate the child process and drain bounded output before the cancellation is re-raised. Handler-level `finally` blocks then remove the operation workspace.

## Concurrency

Media execution is protected by an asyncio semaphore. This bounds concurrent media subprocesses across callers of the same `MediaService` instance and reduces simultaneous disk pressure.

## Disk exhaustion

A free-space guard is checked before workspace allocation and before/during media subprocess execution. A low-free-space condition terminates the media operation with `ResourceError` rather than allowing an unbounded write to continue. The workspace-size gate remains an independent per-operation bound.

## Cleanup

All seven Phase 7 media consumers retain unique operation workspaces and clean them in `finally` paths:

```text
plugins/media/ffmpeg.py
plugins/advanced/mediaflow.py
plugins/media_ops/video.py
plugins/media_ops/speech.py
plugins/media_ops/stream.py
plugins/media/aria2.py
plugins/media/rclone.py
```

Cleanup therefore runs after success, command failure, media failure, upload failure, and propagated cancellation when the handler unwinds.

## Rclone

Only `copy`, `copyto`, and `sync` are permitted through `MediaService`. The plugin validates operation and argument shape before invoking the service. Rclone remains a network-capable operation and is not falsely described as isolated media decoding.

## TTS

TTS remains outside the isolated decoder path because it requires network access. Text and voice bounds are enforced by the plugin/service boundary, execution uses the shared bounded subprocess service, and the resulting artifact is verified and cleaned up.

## Dedicated audit

Run:

```bash
./venv/bin/python tools/media_pipeline_audit.py
```

The gate covers:

- consumer/service boundary
- resource limits
- actual isolated FFmpeg transformation
- artifact verification
- malformed-media rejection
- duration-limit rejection
- subprocess cancellation
- temporary workspace cleanup
- disk exhaustion behavior
- bounded concurrency

The audit requires `bwrap`, `prlimit`, `ffmpeg`, and `ffprobe` for the actual transform gate. Optional consumers such as `yt-dlp`, `aria2c`, `rclone`, and `edge-tts` remain capability-gated by their individual plugin setup paths.
