"""Supported, typed plugin-facing API for AstraUserbot.

This module is a facade over existing core contracts. It adds no registry,
lifecycle, or authorization mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeAlias

from core.plugins.capabilities import CAPABILITIES as CAPABILITY_NAMES, validate_capabilities
from core.plugins.contract import PLUGIN_API_VERSION, PluginMetadata as RuntimePluginMetadata
from core.plugins.manager import PluginManager
from core.registry import register_cmd as register_command
from core.services.jobs import ReconcileContext, ReconcileOutcome, Reconciler
from core.services.http import HttpResponse
from core.tasks import TaskSupervisor

SDK_API_VERSION = "1.0"
Capability: TypeAlias = Literal[
    "telegram.read", "telegram.write", "network.external", "fs.read", "fs.write",
    "subprocess", "jobs.enqueue", "ai.remote", "ai.local", "vault.read", "vault.write",
]
CapabilityMode: TypeAlias = Literal["ENFORCED", "LEGACY_UNDECLARED"]
# Effect labels remain runtime strings; this alias creates no second vocabulary.
EffectClass: TypeAlias = str


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    """Validated SDK view of the canonical runtime metadata contract."""
    name: str
    version: str = "legacy"
    api_version: int = PLUGIN_API_VERSION
    description: str = ""
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    critical: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name.strip()) > 256:
            raise ValueError("plugin name must be 1..256 characters")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.version, str) or not self.version.strip() or len(self.version.strip()) > 64:
            raise ValueError("plugin version must be 1..64 characters")
        object.__setattr__(self, "version", self.version.strip())
        version: Any = self.api_version
        if isinstance(version, str):
            if version != SDK_API_VERSION:
                raise ValueError(f"unsupported plugin API version: {version}")
            version = PLUGIN_API_VERSION
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("api_version must be an integer or supported SDK version string")
        if version != PLUGIN_API_VERSION:
            raise ValueError(f"unsupported plugin api version: {version}")
        object.__setattr__(self, "api_version", version)
        if not isinstance(self.description, str) or len(self.description.strip()) > 512:
            raise ValueError("plugin description must be at most 512 characters")
        object.__setattr__(self, "description", self.description.strip())
        for field_name in ("dependencies", "optional_dependencies"):
            value = getattr(self, field_name)
            if isinstance(value, str) or not isinstance(value, (tuple, list)):
                raise ValueError(f"{field_name} must be a sequence of unique strings")
            normalized = tuple(item.strip() if isinstance(item, str) else item for item in value)
            if any(not isinstance(item, str) or not item or len(item) > 128 for item in normalized):
                raise ValueError(f"{field_name} contains an invalid item")
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{field_name} contains duplicates")
            object.__setattr__(self, field_name, normalized)
        object.__setattr__(self, "capabilities", validate_capabilities(self.capabilities))
        if not isinstance(self.critical, bool):
            raise ValueError("critical must be a boolean")

    def to_runtime_contract(self) -> RuntimePluginMetadata:
        return RuntimePluginMetadata(
            name=self.name, version=self.version, api_version=self.api_version,
            description=self.description, dependencies=self.dependencies,
            optional_dependencies=self.optional_dependencies, capabilities=self.capabilities,
            critical=self.critical,
        )

    def to_module_metadata(self) -> dict[str, Any]:
        return {
            "plugin_name": self.name, "plugin_version": self.version,
            "plugin_api_version": self.api_version, "plugin_description": self.description,
            "dependencies": self.dependencies, "optional_dependencies": self.optional_dependencies,
            "capabilities": self.capabilities, "critical": self.critical,
        }


def metadata(**kwargs: Any) -> PluginMetadata:
    """Construct validated metadata matching the runtime contract."""
    return PluginMetadata(**kwargs)


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
