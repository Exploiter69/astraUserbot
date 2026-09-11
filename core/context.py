"""Explicit runtime dependency container and service lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol, TypeVar

from core.services import CacheService, HttpService, JobEngine, MediaService, SecretStore, StorageService, SubprocessService, TelegramFacade, WorkspaceService
from core.services.ai import AIService

logger = logging.getLogger("astra.context")

T = TypeVar("T")
_application_context: "ApplicationContext | None" = None


class ManagedService(Protocol):
    async def start(self) -> Any: ...
    async def close(self) -> Any: ...


class ApplicationContext:
    """Own process-wide services and make their lifecycle explicit."""

    def __init__(self, client: Any, project_root: str | Path) -> None:
        self.client = client
        self.project_root = Path(project_root).resolve()
        self.services: dict[str, Any] = {}
        self._started: list[str] = []
        self._closed = False

        self.register("storage", StorageService(self.project_root))
        self.register("cache", CacheService(self.project_root))
        self.register("http", HttpService())
        self.register("subprocess", SubprocessService())
        self.register("telegram", TelegramFacade(client))
        self.register("workspace", WorkspaceService(self.project_root))
        self.register("media", MediaService(self.get("workspace"), self.get("subprocess")))
        self.register("jobs", JobEngine(self.get("storage")))
        self.register("secrets", SecretStore())
        self.register("ai", AIService(self.get("http")))

    def register(self, name: str, service: Any) -> Any:
        if not name or name in self.services:
            raise ValueError(f"Service already registered: {name}")
        self.services[name] = service
        return service

    def get(self, name: str) -> Any:
        return self.services[name]

    def require(self, service_type: type[T]) -> T:
        for service in self.services.values():
            if isinstance(service, service_type):
                return service
        raise LookupError(f"Service not registered: {service_type.__name__}")

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("ApplicationContext is closed")
        for name, service in self.services.items():
            starter = getattr(service, "start", None)
            if starter is None:
                continue
            try:
                await starter()
                self._started.append(name)
            except Exception:
                logger.error("Failed to start service name=%s", name, exc_info=True)
                await self.close()
                raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for name in reversed(self._started):
            service = self.services[name]
            closer = getattr(service, "close", None)
            if closer is None:
                continue
            try:
                await closer()
            except Exception:
                logger.error("Failed to close service name=%s", name, exc_info=True)
        self._started.clear()

    def snapshot(self) -> dict[str, str]:
        return {
            "state": "CLOSED" if self._closed else "RUNNING",
            "services": ",".join(self.services),
        }


def set_application_context(context: ApplicationContext | None) -> None:
    global _application_context
    _application_context = context


def get_application_context() -> ApplicationContext | None:
    return _application_context
