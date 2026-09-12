"""Controlled process-level shutdown probe for the Phase 18 gate.

The child starts the real ApplicationContext and a real JobEngine worker, then
requests normal context shutdown while one job deliberately ignores
cancellation. Production cleanup must return within its bounded application
budget; the deliberately abandoned asyncio tasks are a process-boundary case,
so the diagnostic exits the child immediately after the real close returns.

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
    import os
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
        started = asyncio.get_running_loop().time()
        await context.close()
        elapsed = asyncio.get_running_loop().time() - started
        print(f"SHUTDOWN_CONTEXT_RETURNED elapsed={elapsed:.3f}s", flush=True)
        if elapsed > 4.0:
            raise RuntimeError(f"bounded shutdown exceeded probe budget: {elapsed:.3f}s")
        # Deliberately bypass asyncio.run's final pending-task cancellation.
        # The stubborn coroutine is the test fixture for the process boundary;
        # production systemd remains the final hard-stop authority.
        os._exit(0)

    asyncio.run(main())
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
    env.update({
        "ASTRA_API_ID": "1",
        "ASTRA_API_HASH": "probe",
        "ASTRA_OWNER_ID": "1",
    })
    try:
        result = subprocess.run(
            [sys.executable, "-c", _CHILD],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=PROBE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        print("=== PHASE 18 SHUTDOWN PROBE ===")
        print(f"timeout_seconds={PROBE_TIMEOUT}")
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr)
        print("SHUTDOWN_PROBE_FAIL: bounded ApplicationContext.close did not return")
        return 1

    print("=== PHASE 18 SHUTDOWN PROBE ===")
    print(f"returncode={result.returncode}")
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    if result.returncode == 0 and "SHUTDOWN_CONTEXT_RETURNED" in result.stdout:
        print("SHUTDOWN_PROBE_PASS")
        return 0
    print("SHUTDOWN_PROBE_FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
