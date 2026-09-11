"""Compatibility wrapper around the shared SubprocessService."""

from __future__ import annotations

import shlex
from collections.abc import Sequence

from core.errors import CommandError, TimeoutError


def _service():
    from core.context import get_application_context

    context = get_application_context()
    if context is None:
        raise CommandError("Subprocess service is not initialized.")
    return context.get("subprocess")


async def run(argv: Sequence[str] | str, timeout: int = 30) -> tuple[int, str, str]:
    """Run through the shared subprocess policy while preserving the legacy return shape."""
    try:
        result = await _service().run(argv, timeout=timeout)
    except TimeoutError as exc:
        raise CommandError(exc.message) from exc
    except Exception as exc:
        raise CommandError("The command could not be executed.") from exc
    return result.returncode, result.stdout, result.stderr
