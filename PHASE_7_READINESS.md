# AstraUserbot — Phase 7 Media Platform Completion

**Status: COMPLETE — LOCAL REGRESSION VERIFIED**

Phase 7 made media a shared runtime platform rather than a collection of plugin-owned temporary-file and subprocess conventions.

## 1. MediaService

Created `core/services/media.py` and registered it in `ApplicationContext`.

The service owns:

- unique per-operation workspaces through `WorkspaceService`;
- bounded input/output/workspace sizes;
- bounded concurrent media execution;
- deterministic subprocess execution through `SubprocessService`;
- explicit artifact validation and manifests;
- FFmpeg execution with explicit argv;
- FFprobe verification when available;
- TTS execution and output verification;
- deterministic download artifact discovery;
- rclone operation policy;
- cleanup through the workspace owner.

Default policy:

```text
max input:      512 MiB
max output:     512 MiB
max workspace:  768 MiB
media workers:  2
FFmpeg timeout: 300s
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

FFmpeg-produced artifacts additionally receive an FFprobe readability check when `ffprobe` is available.

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

## 7. Regression Coverage

`tests/test_media_service.py` covers isolated workspace/artifact lifecycle, input size enforcement, artifact rejection, explicit FFmpeg argv construction, FFprobe verification, bounded concurrent execution and rclone policy enforcement.

## 8. Final Gate

```text
MediaService exists                         PASS
all seven consumers use it                 PASS
unique operation workspaces                PASS
deterministic outputs                      PASS
media input/output/workspace limits        PASS
bounded media concurrency                  PASS
cleanup in migrated consumers              PASS
explicit artifact verification             PASS
FFmpeg argv-only execution                 PASS
rclone policy boundary                     PASS
media regression coverage                  PASS
full regression                            PASS
compile validation                         PASS
```

**Final result: 81/81 tests passed, 0 failures, 0 errors, and compile validation passed.**

## Next Phase

The canonical next phase is **Phase 8 — AI Gateway**, now implemented in `core/services/ai.py` with command adapters under `plugins/ai_gateway/`. See `PHASE_8_READINESS.md` for the completion record and final local verification command.
