"""Harness-only service substitution for isolated runtime tests.

This adapter deliberately lives outside core.context: production
ApplicationContext keeps its normal construction and lifecycle behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.context import ApplicationContext


class HarnessApplicationContext(ApplicationContext):
    """ApplicationContext variant that substitutes services at registration.

    Overrides are installed by register while ApplicationContext.__init__
    is building the service graph. Therefore dependent services resolve the
    substitute through self.get rather than capturing the discarded default.
    No production service-factory seam is required.
    """

    def __init__(
        self,
        client: Any,
        project_root: str | Path,
        *,
        service_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self._service_overrides = dict(service_overrides or {})
        self._installed_service_overrides: set[str] = set()
        super().__init__(client, project_root)
        unknown = set(self._service_overrides) - self._installed_service_overrides
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"Unknown service override(s): {names}")

    def register(self, name: str, service: Any) -> Any:
        if name in self._service_overrides:
            service = self._service_overrides[name]
            self._installed_service_overrides.add(name)
        return super().register(name, service)
