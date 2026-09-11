"""Deterministic plugin discovery, lifecycle, dependency and ownership management.

This is intentionally small: AstraUserbot remains a single-process modular
monolith. Legacy plugins that expose ``setup(client)`` continue to work while
newer plugins may expose metadata and an optional async ``shutdown(client)``.
"""

from __future__ import annotations

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
    critical: bool = False
    error: str | None = None
    registrations: set[str] = field(default_factory=set)


class PluginError(RuntimeError):
    """Base error for deterministic plugin lifecycle failures."""


class PluginDependencyError(PluginError):
    """Raised when plugin dependencies cannot be satisfied."""


class PluginManager:
    """Own plugin discovery and lifecycle without changing plugin behavior."""

    # The Phase 8 command adapters live in plugins/ai_gateway. These legacy
    # Groq-specific command modules remain in the tree as a compatibility
    # reference but must not register duplicate commands at runtime.
    _QUARANTINED_MODULES = frozenset({
        "plugins.ai.ask",
        "plugins.ai.summarize",
        "plugins.ai.transcribe",
    })

    _current_plugin: ContextVar[str | None] = ContextVar(
        "astra_current_plugin", default=None
    )
    _current_manager: ContextVar["PluginManager | None"] = ContextVar(
        "astra_current_plugin_manager", default=None
    )

    def __init__(self, client: Any, plugin_root: Path):
        self.client = client
        self.plugin_root = plugin_root.resolve()
        self.project_root = self.plugin_root.parent
        self.records: dict[str, PluginRecord] = {}
        self._disabled: set[str] = set()
        self._load_order: list[str] = []

    @classmethod
    def current_plugin(cls) -> str | None:
        """Return the plugin whose setup/lifecycle code is currently executing."""
        return cls._current_plugin.get()

    @classmethod
    def current_manager(cls) -> "PluginManager | None":
        """Return the manager bound to the current plugin lifecycle context."""
        return cls._current_manager.get()

    @classmethod
    @contextmanager
    def plugin_context(cls, name: str, manager: "PluginManager | None" = None) -> Iterator[None]:
        """Bind plugin and manager ownership for out-of-band registration setup."""
        token_plugin = cls._current_plugin.set(name)
        token_manager = cls._current_manager.set(manager)
        try:
            yield
        finally:
            cls._current_manager.reset(token_manager)
            cls._current_plugin.reset(token_plugin)

    def _plugin_context(self, name: str) -> Iterator[None]:
        """Bind this manager and plugin for lifecycle execution."""
        return self.plugin_context(name, self)

    def discover(self) -> list[PluginRecord]:
        """Discover Python plugin modules in deterministic path order."""
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

    def _module_name(self, path: Path) -> str:
        relative = path.relative_to(self.project_root).with_suffix("")
        return ".".join(relative.parts)

    def _read_metadata(self, record: PluginRecord) -> None:
        module = record.module
        if module is None:
            return
        dependencies = getattr(module, "dependencies", ())
        if isinstance(dependencies, str):
            dependencies = (dependencies,)
        record.dependencies = tuple(str(dep) for dep in dependencies)
        record.critical = bool(getattr(module, "critical", False))

    def _dependency_order(self) -> list[str]:
        """Topologically sort discovered plugins with deterministic tie-breaking."""
        graph = {
            name: set(record.dependencies)
            for name, record in self.records.items()
        }
        unknown = sorted(
            {dep for deps in graph.values() for dep in deps if dep not in graph}
        )
        if unknown:
            raise PluginDependencyError(
                "Unknown plugin dependencies: " + ", ".join(unknown)
            )

        order: list[str] = []
        while graph:
            ready = sorted(name for name, deps in graph.items() if not deps)
            if not ready:
                cycle = ", ".join(sorted(graph))
                raise PluginDependencyError(
                    f"Plugin dependency cycle detected: {cycle}"
                )
            order.extend(ready)
            for name in ready:
                graph.pop(name)
            for deps in graph.values():
                deps.difference_update(ready)
        return order

    async def load_all(self) -> list[PluginRecord]:
        """Import and initialize every discovered, non-disabled plugin."""
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
            setup = getattr(record.module, "setup", None)
            if setup is None:
                record.state = PluginState.RUNNING
                continue
            token_plugin = self._current_plugin.set(name)
            token_manager = self._current_manager.set(self)
            try:
                logger.info("Setting up plugin: %s", name)
                result = setup(self.client)
                if inspect.isawaitable(result):
                    await result
                record.state = PluginState.RUNNING
                record.error = None
            except Exception as exc:
                record.state = PluginState.FAILED_SETUP
                record.error = str(exc)
                logger.error("Failed to setup plugin %s: %s", name, exc, exc_info=True)
                if record.critical:
                    raise
            finally:
                self._current_manager.reset(token_manager)
                self._current_plugin.reset(token_plugin)

        self._log_report()
        return list(self.records.values())

    async def unload(self, name: str) -> PluginRecord:
        """Run shutdown and remove all registrations owned by the plugin."""
        record = self.records[name]
        if record.module is not None:
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
        try:
            from core.registry import unregister_owner
            unregister_owner(name)
        except ImportError:
            logger.exception("Could not clean registrations for plugin %s", name)
        record.registrations.clear()
        record.state = PluginState.UNLOADED
        return record

    def disable(self, name: str) -> None:
        self._disabled.add(name)
        if name in self.records:
            self.records[name].state = PluginState.DISABLED

    def enable(self, name: str) -> None:
        self._disabled.discard(name)

    def startup_report(self) -> dict[str, str]:
        return {name: record.state.value for name, record in sorted(self.records.items())}

    def _log_report(self) -> None:
        summary = ", ".join(
            f"{name}={record.state.value}"
            for name, record in sorted(self.records.items())
        )
        logger.info("Plugin startup report: %s", summary)

    async def shutdown(self) -> None:
        """Unload running plugins in reverse load order."""
        for name in reversed(self._load_order):
            record = self.records.get(name)
            if record and record.state == PluginState.RUNNING:
                try:
                    await self.unload(name)
                except Exception:
                    logger.exception("Plugin shutdown failed: %s", name)
