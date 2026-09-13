# AstraUserbot — Isolation / Security Hardening

**Status:** Implementation complete; local gate required  
**Cost target:** ₹0 / $0

## Security boundary

Astra plugins remain same-process and are not sandboxed merely because Bubblewrap exists. The reviewed isolation boundary is an explicit child-process executor in `core/services/isolation.py`.

When a workload requires isolation, the executor:

- requires Bubblewrap rather than silently degrading;
- creates a separate PID, mount, IPC, UTS, cgroup, and network namespace through `--unshare-all`;
- uses `--clearenv` and a minimal environment;
- exposes only required system runtime trees read-only;
- exposes exactly one caller-owned workspace at `/workspace` read-write;
- gives the child a private `/tmp` and `/dev`/`/proc` runtime view;
- applies CPU, address-space, file-size, process-count, and file-descriptor limits;
- uses argv semantics, never shell interpolation;
- bounds stdout/stderr and kills timed-out or cancelled children.

Network access is disabled for isolated workloads. A network-requiring operation such as rclone or a remote downloader must use the ordinary bounded subprocess path with its own explicit network policy rather than pretending to be isolated.

## Eval

`.eval` remains an owner-level privileged command. It now runs through the real isolation executor and Python isolated mode. The evaluated child cannot see the application home tree, configured environment secrets, or the host network. A timeout or cancellation kills the child process.

Isolation does not make arbitrary Python safe inside the namespace; it reduces the blast radius of the child. The command remains high-risk and is not a general-purpose public execution feature.

## Media

Media decoding/conversion is an untrusted-input boundary. FFmpeg and ffprobe executions use the isolated executor and the existing workspace/input/output bounds. OCR uses the same boundary through the media service. Network-enabled media operations remain separate because they require explicit network access.

## Filesystem

`WorkspaceService` canonicalizes paths and rejects traversal outside its managed root. Cleanup cannot remove the root itself. The archive helper additionally rejects absolute/traversal members, symlinks, hardlinks, devices, FIFOs, oversized members, excessive entry counts, and excessive total extraction size.

## Secrets

Isolated processes start with a cleared environment and only a minimal allowlist. The shared subprocess service does not log environment values or command output. User-facing failures are bounded and must not include credentials.

## Validation

`tools/isolation_security_audit.py` performs both static checks and live probes when Bubblewrap and ffprobe are available:

- actual isolated execution;
- filesystem boundary;
- network isolation;
- environment clearing;
- subprocess timeout containment;
- malformed-media decoder containment;
- ZIP traversal rejection;
- TAR symlink rejection;
- safe archive extraction;
- argv-only subprocess policy;
- `.eval` isolation wiring;
- OCR/media isolation wiring.

The permanent regression suite is `tests/test_isolation_security.py`.

## Non-goals

This is not a kernel security certification and does not claim protection against a compromised kernel, privileged host account, or vulnerabilities in the isolation backend itself. It is a deterministic application boundary for untrusted child workloads, with fail-closed behavior when the reviewed backend is unavailable.
