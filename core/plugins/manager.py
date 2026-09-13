"""Deterministic plugin discovery, lifecycle, dependency and ownership management.

This remains deliberately small. Legacy ``setup(client)`` modules are adapted
to the formal metadata contract, while lifecycle mutations are transactional:
a disable removes owned registrations only after shutdown succeeds, and an
enable validates dependencies and rolls back registrations if setup fails.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, AsyncIterator, Iterator

from core.plugins.contract import PluginMetadata, metadata_for

logger = logging.getLogger("astra.plugins")


class PluginState(str, Enum):
    DISCOVERED = "DISCOVERED"
    LOADED = "LOADED"
    RUNNING = "RUNNING"
    FAILED_IMPORT = "FAILED_IMPORT"
    FAILED_SETUP = "FAILED_SETUP"
    DISABLED = "DISABLED"
    UNLOADED = "UNLOADED"


@dataclass(slots=True)
class PluginRecord:
    name: str
    module: ModuleType | None = None
    state: PluginState = PluginState.DISCOVERED
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    version: str = "legacy"
    api_version: int = 1
    description: str = ""
    critical: bool = False
    error: str | None = None
    registrations: set[str] = field(default_factory=set)


class PluginError(RuntimeError):
    """Base error for deterministic plugin lifecycle failures."""


class PluginDependencyError(PluginError):
    """Raised when plugin dependencies cannot be satisfied."""


class PluginLifecycleError(PluginError):
    """Raised when a lifecycle mutation cannot be completed safely."""


class PluginManager:
    """Own plugin discovery and lifecycle without changing plugin behavior."""

    _QUARANTINED_MODULES = frozenset({
        "plugins.ai.ask",
        "plugins.ai.summarize",
        "plugins.ai.transcribe",
        "plugins.ai.groq_client",
    })
    _SHUTDOWN_BUDGET_SECONDS = 2.5
    _PLUGIN_MUTATION_TIMEOUT_SECONDS = 5.0

    _current_plugin: ContextVar[str | None] = ContextVar("astra_current_plugin", default=None)
    _current_manager: ContextVar["PluginManager | None"] = ContextVar("astra_current_plugin_manager", default=None)

    def __init__(self, client: Any, plugin_root: Path):
        self.client = client
        self.plugin_root = plugin_root.resolve()
        self.project_root = self.plugin_root.parent
        self.records: dict[str, PluginRecord] = {}
        self._disabled: set[str] = set()
        self._load_order: list[str] = []

    @classmethod
    def current_plugin(cls) -> str | None:
        return cls._current_plugin.get()

    @classmethod
    def current_manager(cls) -> "PluginManager | None":
        return cls._current_manager.get()

    @classmethod
    @contextmanager
    def plugin_context(cls, name: str, manager: "PluginManager | None" = None) -> Iterator[None]:
        token_plugin = cls._current_plugin.set(name)
        token_manager = cls._current_manager.set(manager)
        try:
            yield
        finally:
            cls._current_manager.reset(token_manager)
            cls._current_plugin.reset(token_plugin)

    def _plugin_context(self, name: str) -> Iterator[None]:
        return self.plugin_context(name, self)

    def discover(self) -> list[PluginRecord]:
        self.records.clear()
        self._load_order.clear()
        if not self.plugin_root.exists():
            logger.warning("Plugin directory %s not found.", self.plugin_root)
            return []
        for path in sorted(self.plugin_root.rglob("*.py")):
            if path.name == "__init__.py" or path.name.startswith("_"):
                continue
            name = self._module_name(path)
            if name in self._QUARANTINED_MODULES:
                logger.info("Quarantining legacy plugin: %s", name)
                continue
            self.records[name] = PluginRecord(name=name)
        logger.info("Discovered %d plugins.", len(self.records))
        return list(self.records.values())

    @property
    def quarantined_modules(self) -> tuple[str, ...]:
        """Return quarantined legacy modules for operator visibility."""
        return tuple(sorted(self._QUARANTINED_MODULES))

    def _module_name(self, path: Path) -> str:
        relative = path.relative_to(self.project_root).with_suffix("")
        return ".".join(relative.parts)

    def _read_metadata(self, record: PluginRecord) -> PluginMetadata:
        metadata = metadata_for(record.module, record.name) if record.module else metadata_for(importlib.import_module(record.name), record.name)
        record.name = metadata.name if metadata.name.startswith("plugins.") else record.name
        record.version = metadata.version
        record.api_version = metadata.api_version
        record.description = metadata.description
        record.dependencies = metadata.dependencies
        record.optional_dependencies = metadata.optional_dependencies
        record.capabilities = metadata.capabilities
        record.critical = metadata.critical
        return metadata

    def _dependency_order(self) -> list[str]:
        graph = {name: set(record.dependencies) for name, record in self.records.items()}
        unknown = sorted({dep for deps in graph.values() for dep in deps if dep not in graph})
        if unknown:
            raise PluginDependencyError("Unknown plugin dependencies: " + ", ".join(unknown))
        order: list[str] = []
        while graph:
            ready = sorted(name for name, deps in graph.items() if not deps)
            if not ready:
                raise PluginDependencyError(f"Plugin dependency cycle detected: {', '.join(sorted(graph))}")
            order.extend(ready)
            for name in ready:
                graph.pop(name)
            for deps in graph.values():
                deps.difference_update(ready)
        return order

    def _validate_dependency_runtime(self, name: str) -> None:
        record = self.records[name]
        missing = [
            dep for dep in record.dependencies
            if dep not in self.records or self.records[dep].state != PluginState.RUNNING
        ]
        if missing:
            raise PluginDependencyError(
                f"Plugin {name} requires running dependencies: {', '.join(missing)}"
            )

    async def _run_setup(self, record: PluginRecord) -> None:
        setup = getattr(record.module, "setup", None)
        if setup is None:
            record.state = PluginState.RUNNING
            record.error = None
            return
        token_plugin = self._current_plugin.set(record.name)
        token_manager = self._current_manager.set(self)
        try:
            logger.info("Setting up plugin: %s", record.name)
            result = setup(self.client)
            if inspect.isawaitable(result):
                await result
            record.state = PluginState.RUNNING
            record.error = None
        finally:
            self._current_manager.reset(token_manager)
            self._current_plugin.reset(token_plugin)

    async def load_all(self) -> list[PluginRecord]:
        if not self.records:
            self.discover()
        for name in sorted(self.records):
            record = self.records[name]
            if name in self._disabled:
                record.state = PluginState.DISABLED
                continue
            try:
                record.module = importlib.import_module(name)
                record.state = PluginState.LOADED
                self._read_metadata(record)
            except Exception as exc:
                record.state = PluginState.FAILED_IMPORT
                record.error = str(exc)
                logger.error("Failed to import plugin %s: %s", name, exc, exc_info=True)
                if record.critical:
                    raise
        try:
            order = self._dependency_order()
        except PluginDependencyError as exc:
            logger.error("Plugin dependency validation failed: %s", exc)
            for record in self.records.values():
                if record.state == PluginState.LOADED:
                    record.state = PluginState.FAILED_SETUP
                    record.error = str(exc)
            raise
        self._load_order = order
        for name in order:
            record = self.records[name]
            if record.state != PluginState.LOADED:
                continue
            try:
                self._validate_dependency_runtime(name)
                await self._run_setup(record)
            except Exception as exc:
                record.state = PluginState.FAILED_SETUP
                record.error = str(exc)
                logger.error("Failed to setup plugin %s: %s", name, exc, exc_info=True)
                if record.critical:
                    raise
        self._log_report()
        return list(self.records.values())

    async def unload(self, name: str) -> PluginRecord:
        if name not in self.records:
            raise PluginLifecycleError(f"Unknown plugin: {name}")
        record = self.records[name]
        if record.state not in {PluginState.RUNNING, PluginState.FAILED_SETUP}:
            return record
        shutdown = getattr(record.module, "shutdown", None)
        if shutdown is not None:
            token_plugin = self._current_plugin.set(name)
            token_manager = self._current_manager.set(self)
            try:
                result = shutdown(self.client)
                if inspect.isawaitable(result):
                    await result
            finally:
                self._current_manager.reset(token_manager)
                self._current_plugin.reset(token_plugin)
        if record.registrations:
            from core.registry import get_registration
            for registration_id in list(record.registrations):
                try:
                    registration = get_registration(registration_id)
                except KeyError:
                    continue
                registration.unregister(self.client)
            record.registrations.clear()
        record.state = PluginState.UNLOADED
        return record

    @staticmethod
    def _consume_background_result(task: asyncio.Task[Any]) -> None:
        if not task.done():
            return
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            return

    async def _bounded_unload(self, name: str, timeout: float) -> None:
        task = asyncio.create_task(self.unload(name), name=f"plugin_shutdown:{name}")
        done, _ = await asyncio.wait({task}, timeout=max(0.0, timeout))
        if task in done:
            try:
                task.result()
            except Exception:
                logger.error("Plugin shutdown failed: %s", name, exc_info=True)
            return
        task.cancel()
        task.add_done_callback(self._consume_background_result)
        logger.error("Plugin shutdown timed out after %.3fs: %s; continuing runtime teardown.", timeout, name)

    async def shutdown(self) -> None:
        names = [name for name in reversed(self._load_order) if self.records[name].state == PluginState.RUNNING]
        deadline = asyncio.get_running_loop().time() + self._SHUTDOWN_BUDGET_SECONDS
        for name in names:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                logger.error("Plugin shutdown budget exhausted; skipping %d plugin(s).", sum(self.records[item].state == PluginState.RUNNING for item in names))
                break
            stage_started = asyncio.get_running_loop().time()
            logger.info("Plugin shutdown starting: %s", name)
            await self._bounded_unload(name, remaining)
            logger.info("Plugin shutdown stage finished: %s in %.3fs", name, asyncio.get_running_loop().time() - stage_started)

    async def disable_plugin(self, name: str) -> PluginRecord:
        """Safely disable a plugin and all of its owned command registrations.

        Dependencies are protected: a plugin cannot be disabled while another
        running plugin requires it. The disabled marker is applied only after
        shutdown succeeds; a failed shutdown therefore leaves the plugin live.
        """
        if name not in self.records:
            raise PluginLifecycleError(f"Unknown plugin: {name}")
        record = self.records[name]
        if record.state == PluginState.DISABLED:
            return record
        dependents = sorted(
            item.name for item in self.records.values()
            if item.state == PluginState.RUNNING and name in item.dependencies
        )
        if dependents:
            raise PluginDependencyError(
                f"Cannot disable {name}; running dependents: {', '.join(dependents)}"
            )
        if record.state == PluginState.RUNNING:
            try:
                await asyncio.wait_for(self.unload(name), timeout=self._PLUGIN_MUTATION_TIMEOUT_SECONDS)
            except Exception as exc:
                record.error = str(exc)
                raise PluginLifecycleError(f"Disable failed for {name}: {exc}") from exc
        self._disabled.add(name)
        record.state = PluginState.DISABLED
        record.error = None
        return record

    async def enable_plugin(self, name: str) -> PluginRecord:
        """Safely enable a disabled plugin, rolling back registrations on failure."""
        if name in self._QUARANTINED_MODULES:
            raise PluginLifecycleError(f"Quarantined plugin cannot be enabled: {name}")
        if name not in self.records:
            raise PluginLifecycleError(f"Unknown plugin: {name}")
        record = self.records[name]
        if record.state == PluginState.RUNNING:
            return record
        if record.state not in {PluginState.DISABLED, PluginState.UNLOADED, PluginState.FAILED_SETUP, PluginState.FAILED_IMPORT, PluginState.DISCOVERED}:
            raise PluginLifecycleError(f"Plugin {name} is not enableable from {record.state.value}")
        self._validate_dependency_runtime(name)
        old_registration_ids = set(record.registrations)
        self._disabled.discard(name)
        try:
            if record.module is None:
                record.module = importlib.import_module(name)
            record.state = PluginState.LOADED
            self._read_metadata(record)
            self._validate_dependency_runtime(name)
            await asyncio.wait_for(self._run_setup(record), timeout=self._PLUGIN_MUTATION_TIMEOUT_SECONDS)
            return record
        except Exception as exc:
            record.state = PluginState.FAILED_SETUP
            record.error = str(exc)
            # Remove any registrations created by the failed setup attempt.
            from core.registry import get_registration
            for registration_id in list(record.registrations - old_registration_ids):
                try:
                    get_registration(registration_id).unregister(self.client)
                except KeyError:
                    pass
                record.registrations.discard(registration_id)
            self._disabled.add(name)
            raise PluginLifecycleError(f"Enable failed for {name}: {exc}") from exc

    def disable(self, name: str) -> None:
        """Compatibility marker for callers that cannot await lifecycle work.

        New code must use ``disable_plugin`` so shutdown and command cleanup are
        completed before the plugin is considered disabled.
        """
        if name in self.records:
            self._disabled.add(name)
            self.records[name].state = PluginState.DISABLED

    def enable(self, name: str) -> None:
        """Compatibility marker; use ``enable_plugin`` for actual activation."""
        self._disabled.discard(name)
        if name in self.records and self.records[name].state == PluginState.DISABLED:
            self.records[name].state = PluginState.DISCOVERED

    def get(self, name: str) -> PluginRecord:
        return self.records[name]

    def snapshot(self) -> list[dict[str, Any]]:
        return [{
            "name": record.name,
            "state": record.state.value,
            "version": record.version,
            "api_version": record.api_version,
            "description": record.description,
            "dependencies": list(record.dependencies),
            "optional_dependencies": list(record.optional_dependencies),
            "capabilities": list(record.capabilities),
            "critical": record.critical,
            "error": record.error,
            "registrations": sorted(record.registrations),
        } for record in sorted(self.records.values(), key=lambda item: item.name)]

    def register_ownership(self, registration: str) -> None:
        owner = self.current_plugin()
        if owner and owner in self.records:
            self.records[owner].registrations.add(registration)

    def _log_report(self) -> None:
        counts: dict[str, int] = {}
        for record in self.records.values():
            counts[record.state.value] = counts.get(record.state.value, 0) + 1
        logger.info("Plugin startup report: %s", ", ".join(f"{state}={counts[state]}" for state in sorted(counts)))


@asynccontextmanager
async def managed_plugins(client: Any, plugin_root: Path) -> AsyncIterator[PluginManager]:
    manager = PluginManager(client, plugin_root)
    await manager.load_all()
    try:
        yield manager
    finally:
        await manager.shutdown()
