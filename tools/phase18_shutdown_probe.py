"""Controlled process-level shutdown probe for the Phase 18 gate.

The parent process hard-kills the child after a bounded wall-clock budget, so a
cancellation-resistant job can never hang the operator's shell. The child
starts the real ApplicationContext and a real JobEngine worker, then requests
normal context shutdown while one job deliberately ignores cancellation.

This is a diagnostic, not a production command. It intentionally does not
connect to Telegram or touch the configured production service.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE_TIMEOUT = 6.0

_CHILD = textwrap.dedent(
    """
    import asyncio
    from pathlib import Path
    from core.context import ApplicationContext

    class FakeClient:
        pass

    async def main():
        context = ApplicationContext(FakeClient(), Path.cwd() / ".phase18-shutdown-probe")
        await context.start()
        jobs = context.get("jobs")
        stop = asyncio.Event()

        async def stubborn(job):
            try:
                await stop.wait()
            except asyncio.CancelledError:
                # Deliberately emulate a cancellation-resistant legacy handler.
                await stop.wait()
            return None

        jobs.register_handler("STUBBORN", stubborn)
        await jobs.enqueue("STUBBORN")
        await asyncio.sleep(0.2)
        await context.close()

    asyncio.run(main())
    print("SHUTDOWN_PROBE_COMPLETED")
    """
).strip()


def main() -> int:
    env = dict(os.environ)
    env.pop("ASTRA_API_ID", None)
    env.pop("API_ID", None)
    env.pop("ASTRA_API_HASH", None)
    env.pop("API_HASH", None)
    env.pop("ASTRA_OWNER_ID", None)
    env.pop("OWNER_ID", None)

    # The child only constructs ApplicationContext; config.py is imported by
    # the registry, so supply harmless probe-only values rather than production
    # credentials. No Telegram client is created.
    env.update({
        "ASTRA_API_ID": "1",
        "ASTRA_API_HASH": "probe",
        "ASTRA_OWNER_ID": "1",
    })
    result = subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=PROBE_TIMEOUT,
        check=False,
    )
    print("=== PHASE 18 SHUTDOWN PROBE ===")
    print(f"returncode={result.returncode}")
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    if "SHUTDOWN_PROBE_COMPLETED" in result.stdout:
        print("SHUTDOWN_PROBE_PASS")
        return 0
    print("SHUTDOWN_PROBE_FAIL")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired as exc:
        print("=== PHASE 18 SHUTDOWN PROBE ===")
        print(f"timeout_seconds={PROBE_TIMEOUT}")
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr)
        print("SHUTDOWN_PROBE_FAIL: child exceeded bounded wall-clock budget")
        raise SystemExit(1)
