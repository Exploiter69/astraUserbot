"""Supported, typed plugin-facing API for AstraUserbot.

This module is a facade over existing core contracts. It adds no registry,
lifecycle, or authorization mechanism.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol, TypeAlias

from core.plugins.capabilities import CAPABILITIES as CAPABILITY_NAMES, validate_capabilities
from core.sdk import SDK_API_VERSION, PluginMetadata, metadata
from core.plugins.manager import PluginManager
from core.registry import register_cmd as register_command
from core.services.jobs import ReconcileContext, ReconcileOutcome, Reconciler
from core.services.http import HttpResponse
from core.tasks import TaskSupervisor

Capability: TypeAlias = Literal[
    "telegram.read", "telegram.write", "network.external", "fs.read", "fs.write",
    "subprocess", "jobs.enqueue", "ai.remote", "ai.local", "vault.read", "vault.write",
]
CapabilityMode: TypeAlias = Literal["ENFORCED", "LEGACY_UNDECLARED"]
# Effect labels remain runtime strings; this alias creates no second vocabulary.
EffectClass: TypeAlias = str


class Plugin(Protocol):
    """Structural plugin contract; inheritance is not required."""
    plugin_name: str
    plugin_version: str
    plugin_api_version: int
    dependencies: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    capabilities: tuple[str, ...]
    description: str
    critical: bool

    def setup(self, client: Any) -> Any: ...


class TelegramService(Protocol):
    async def send_message(self, entity: Any, message: str, **kwargs: Any) -> Any: ...
    async def edit_message(self, entity: Any, message: Any, text: str, **kwargs: Any) -> Any: ...
    async def get_messages(self, entity: Any, *, limit: int = 100, **kwargs: Any) -> list[Any]: ...


class HTTPService(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> HttpResponse: ...
    async def get(self, url: str, **kwargs: Any) -> HttpResponse: ...
    async def post(self, url: str, **kwargs: Any) -> HttpResponse: ...


class JobService(Protocol):
    def register_handler(self, job_type: str, handler: Any, *, effect_class: EffectClass | None = None, reconciler: Reconciler | None = None) -> None: ...
    async def enqueue(self, job_type: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> Any: ...


class StorageServiceProtocol(Protocol):
    async def fetchall(self, query: str, parameters: tuple[Any, ...] = ()) -> list[Any]: ...
    async def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> Any: ...


class SecretStoreService(Protocol):
    async def get(self, name: str) -> str | None: ...


class AIServiceProtocol(Protocol):
    async def chat(self, messages: Any, *, model: str | None = None, provider: str | None = None, temperature: float = 0.7) -> Any: ...


class SubprocessServiceProtocol(Protocol):
    async def run(self, *args: Any, **kwargs: Any) -> Any: ...


def _active_manager() -> PluginManager:
    manager = PluginManager.current_manager()
    if manager is None:
        raise RuntimeError("Tracked resources are available only during plugin setup")
    return manager


def tracked_task(supervisor: TaskSupervisor, awaitable: Any, *, name: str) -> Any:
    return _active_manager().tracked_task(supervisor, awaitable, name=name)


async def tracked_job(jobs: Any, job_type: str, payload: dict[str, Any] | None = None,
                      *, owner: str | None = None, **enqueue_options: Any) -> Any:
    return await _active_manager().tracked_job(
        jobs, job_type, payload, owner=owner, **enqueue_options
    )


def tracked_resource(factory: Any, cleanup: Any, *, kind: str,
                     identity: str | None = None) -> Any:
    return _active_manager().tracked_resource(factory, cleanup, kind=kind, identity=identity)


__all__ = [
    "AIServiceProtocol", "Capability", "CapabilityMode", "CAPABILITY_NAMES",
    "EffectClass", "HTTPService", "HttpResponse", "JobService", "Plugin",
    "PluginMetadata", "ReconcileContext", "ReconcileOutcome", "Reconciler",
    "SDK_API_VERSION", "SecretStoreService", "StorageServiceProtocol",
    "SubprocessServiceProtocol", "TelegramService", "metadata", "register_command",
    "tracked_job", "tracked_resource", "tracked_task", "validate_capabilities",
]
