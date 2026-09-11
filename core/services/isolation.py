from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IsolationAssessment:
    enabled: bool
    backend: str
    reason: str


class IsolationService:
    """Conservative isolation policy; never pretends a Python plugin is sandboxed."""

    def __init__(self) -> None:
        self._started = False
        self._backend = "none"
        self._reason = "No isolation backend enabled; plugins remain same-process and therefore same-trust."

    async def start(self) -> None:
        if shutil.which("bwrap"):
            self._backend = "bubblewrap-available"
            self._reason = "Bubblewrap is available but opt-in activation is intentionally disabled until a measured untrusted workload requires it."
        elif shutil.which("firejail"):
            self._backend = "firejail-available"
            self._reason = "Firejail is available but opt-in activation is intentionally disabled until a measured untrusted workload requires it."
        self._started = True

    async def close(self) -> None:
        self._started = False

    def assess(self) -> IsolationAssessment:
        return IsolationAssessment(False, self._backend, self._reason)

    def require_explicit_backend(self) -> None:
        raise RuntimeError("Isolation is not implicitly enabled; select and configure a reviewed backend for a measured workload.")
