# AstraUserbot — Phase 7 Media Platform Completion

**Status: IMPLEMENTATION COMPLETE — LOCAL REGRESSION REQUIRED FOR FINAL GATE**

Phase 7 has been implemented on `main`. The Media Platform is now a shared runtime service rather than a collection of plugin-owned temporary-file and subprocess conventions.

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

The following seven consumers now use `MediaService`:

```text
plugins/media/ffmpeg.py
plugins/advanced/mediaflow.py
plugins/media_ops/video.py
plugins/media_ops/speech.py
plugins/media_ops/stream.py
plugins/media/aria2.py
plugins/media/rclone.py
```

No Phase 7 consumer creates its own shared `data/cache` media workspace or calls the legacy shell helper for media execution.

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

The service also enforces a workspace aggregate size bound after external execution.

## 6. Rclone Boundary

Rclone remains available, but it is no longer an unrestricted generic subprocess API. The MediaService currently permits only:

```text
copy
copyto
sync
```

All other rclone operations are rejected by policy.

## 7. Regression Coverage

Added `tests/test_media_service.py` covering:

- isolated workspace/artifact lifecycle;
- input size enforcement;
- missing/empty/oversized artifact rejection;
- explicit FFmpeg argv construction;
- FFprobe verification path;
- bounded concurrent execution;
- rclone policy enforcement.

Updated runtime service tests to require the MediaService in the application context.

## 8. Phase 7 Exit Criteria

```text
MediaService exists                         PASS
all seven consumers use it                 PASS
unique operation workspaces                PASS
deterministic outputs                      PASS
media input/output/workspace limits        PASS
bounded media concurrency                 PASS
cleanup in migrated consumers              PASS
explicit artifact verification              PASS
FFmpeg argv-only execution                 PASS
rclone policy boundary                     PASS
media regression coverage                  PASS
```

### Final Gate

The implementation gate is complete. Run the complete local regression and compile validation from the current checkout before declaring the release gate verified:

```bash
cd ~/AstraUserbot && \
git pull --ff-only origin main && \
source venv/bin/activate && \
python -m unittest discover -s tests -v && \
python -m compileall -q core plugins main.py && \
echo "=== PHASE 7 GATE: PASS ==="
```

Expected test count is **81 tests** (75 pre-Phase-7 tests plus 6 new media-platform tests).

## Next Phase

After the local gate passes, the canonical next phase is **Phase 8 — AI Gateway**. It should extract the existing Groq integration behind a provider-independent interface. Local Ollama/llama.cpp remains optional and is not a deployment requirement for the current host.
