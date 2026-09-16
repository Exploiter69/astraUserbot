"""Explicit runtime dependency container and service lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol, TypeVar

from config import config
from core.services import (
    AutomationEngine,
    CacheService,
    HttpService,
    IntelGraph,
    JobEngine,
    MediaService,
    SecretStore,
    StorageService,
    SubprocessService,
    TelegramArchiveService,
    TelegramEventCollector,
    TelegramEventJournal,
    TelegramEventProjections,
    TelegramEventReplay,
    TelegramFacade,
    TelegramStateCache,
    WorkspaceService,
)
from core.services.ai import AIService
from core.services.flags import FeatureFlagService
from core.services.isolation import IsolationService
from core.services.metrics import MetricsService
from core.services.search import SearchService
from core.services.telegram_recorder import TelegramOperationRecorder
from core.tasks import TaskSupervisor

logger = logging.getLogger("astra.context")
T = TypeVar("T")
_application_context: ApplicationContext | None = None


class ManagedService(Protocol):
    async def start(self) -> Any: ...
    async def close(self) -> Any: ...


class ApplicationContext:
    """Own process-wide services and make their lifecycle explicit."""

    def __init__(self, client: Any, project_root: str | Path) -> None:
        self.client = client
        self.project_root = Path(project_root).resolve()
        self.services: dict[str, Any] = {}
        self.tasks = TaskSupervisor()
        self._started: list[str] = []
        self._closed = False
        self.register("storage", StorageService(self.project_root))
        self.register("cache", CacheService(self.project_root))
        self.register("http", HttpService())
        self.register("subprocess", SubprocessService())
        self.register("telegram_state", TelegramStateCache(self.get("storage")))
        self.register("telegram", TelegramFacade(client, recorder=TelegramOperationRecorder(self.get("storage")), state_cache=self.get("telegram_state")))
        self.register("telegram_event_journal", TelegramEventJournal(self.get("storage")))
        self.register("telegram_events", TelegramEventCollector(client))
        self.register("telegram_event_projections", TelegramEventProjections(self.get("storage"), self.get("telegram_event_journal")))
        self.register("telegram_event_replay", TelegramEventReplay(self.get("storage"), self.get("telegram_event_journal"), self.get("telegram_event_projections")))
        self.get("telegram_events").add_sink(self.get("telegram_event_journal").append)
        self.get("telegram_events").add_sink(self._project_event)
        self.register("intelgraph", IntelGraph(self.get("storage")))
        self.register("workspace", WorkspaceService(self.project_root))
        self.register("isolation", IsolationService())
        self.register("media", MediaService(self.get("workspace"), self.get("subprocess"), self.get("isolation")))
        self.register("jobs", JobEngine(self.get("storage")))
        self.register("automation", AutomationEngine(self.get("storage"), self.get("jobs"), self.get("telegram"), owner_id=config.OWNER_ID))
        self.get("telegram_events").add_sink(self.get("automation").trigger)
        self.register("secrets", SecretStore())
        self.register("ai", AIService(self.get("http")))
        self.register("search", SearchService(self.get("storage"), self.project_root))
        self.register(
            "telegram_archive",
            TelegramArchiveService(
                self.get("storage"),
                self.get("telegram"),
                self.get("search"),
                self.get("media"),
                self.get("jobs"),
                self.project_root,
            ),
        )
        self.register("metrics", MetricsService(self.project_root))
        self.register("flags", FeatureFlagService(self.get("storage")))

    async def _project_event(self, _event: Any) -> None:
        if not self.get("telegram_event_projections")._started:
            return
        await self.get("telegram_event_projections").process_pending(limit=1)

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
                logger.exception("Failed to start service name=%s", name)
                await self.close()
                raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.tasks.shutdown()
        for name in reversed(self._started):
            service = self.services[name]
            closer = getattr(service, "close", None)
            if closer is None:
                continue
            try:
                await closer()
            except Exception:
                logger.exception("Failed to close service name=%s", name)
        self._started.clear()

    def snapshot(self) -> dict[str, Any]:
        return {"state": "CLOSED" if self._closed else "RUNNING", "services": ",".join(self.services), "task_count": len(self.tasks.active())}


def set_application_context(context: ApplicationContext | None) -> None:
    global _application_context
    _application_context = context


def get_application_context() -> ApplicationContext | None:
    return _application_context
