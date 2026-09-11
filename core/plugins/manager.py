"""Deterministic plugin discovery, lifecycle, dependency and ownership management.

This is intentionally small: AstraUserbot remains a single-process modular
monolith. Legacy plugins that expose ``setup(client)`` continue to work while
newer plugins may expose metadata and an optional async ``shutdown(client)``.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, AsyncIterator

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

    _current_plugin: ContextVar[str | None] = ContextVar(
        "astra_current_plugin", default=None
    )

    def __init__(self, client: Any, plugin_root: Path):
        self.client = client
        self.plugin_root = plugin_root.resolve()
        self.project_root = self.plugin_root.parent
        self.records: dict[str, PluginRecord] = {}
        self._disabled: set[str] = set()

    @classmethod
    def current_plugin(cls) -> str | None:
        """Return the plugin whose setup/lifecycle code is currently executing."""
        return cls._current_plugin.get()

    def discover(self) -> list[PluginRecord]:
        """Discover Python plugin modules in deterministic path order."""
        self.records.clear()
        if not self.plugin_root.exists():
            logger.warning("Plugin directory %s not found.", self.plugin_root)
            return []

        for path in sorted(self.plugin_root.rglob("*.py")):
            if path.name == "__init__.py" or path.name.startswith("_"):
                continue
            name = self._module_name(path)
            record = PluginRecord(name=name)
            self.records[name] = record

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

        # Import first so dependency metadata is available before setup order.
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

        for name in order:
            record = self.records[name]
            if record.state != PluginState.LOADED:
                continue
            setup = getattr(record.module, "setup", None)
            if setup is None:
                # Keep legacy behavior: import-only modules are harmless, but
                # they are not reported as running plugins.
                record.state = PluginState.RUNNING
                continue
            token = self._current_plugin.set(name)
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
                self._current_plugin.reset(token)

        self._log_report()
        return list(self.records.values())

    async def unload(self, name: str) -> PluginRecord:
        """Run plugin shutdown hook and mark the plugin unloaded.

        Event-handler deregistration is deliberately delegated to the command
        router/registration layer; the manager only owns plugin lifecycle.
        """
        record = self.records[name]
        if record.state not in {PluginState.RUNNING, PluginState.FAILED_SETUP}:
            return record
        shutdown = getattr(record.module, "shutdown", None)
        if shutdown is not None:
            token = self._current_plugin.set(name)
            try:
                result = shutdown(self.client)
                if inspect.isawaitable(result):
                    await result
            finally:
                self._current_plugin.reset(token)
        record.state = PluginState.UNLOADED
        return record

    async def shutdown(self) -> None:
        """Unload running plugins in reverse dependency order."""
        running = [name for name, record in self.records.items() if record.state == PluginState.RUNNING]
        for name in reversed(running):
            try:
                await self.unload(name)
            except Exception:
                logger.error("Plugin shutdown failed: %s", name, exc_info=True)

    def disable(self, name: str) -> None:
        if name in self.records:
            self._disabled.add(name)
            self.records[name].state = PluginState.DISABLED

    def enable(self, name: str) -> None:
        self._disabled.discard(name)
        if name in self.records and self.records[name].state == PluginState.DISABLED:
            self.records[name].state = PluginState.DISCOVERED

    def get(self, name: str) -> PluginRecord:
        return self.records[name]

    def snapshot(self) -> list[dict[str, Any]]:
        """Return safe, serialization-friendly lifecycle information."""
        return [
            {
                "name": record.name,
                "state": record.state.value,
                "dependencies": list(record.dependencies),
                "critical": record.critical,
                "error": record.error,
                "registrations": sorted(record.registrations),
            }
            for record in sorted(self.records.values(), key=lambda item: item.name)
        ]

    def register_ownership(self, registration: str) -> None:
        """Associate a command/event registration with the active plugin."""
        owner = self.current_plugin()
        if owner and owner in self.records:
            self.records[owner].registrations.add(registration)

    def _log_report(self) -> None:
        counts: dict[str, int] = {}
        for record in self.records.values():
            counts[record.state.value] = counts.get(record.state.value, 0) + 1
        logger.info("Plugin startup report: %s", ", ".join(
            f"{state}={counts[state]}" for state in sorted(counts)
        ))


@asynccontextmanager
async def managed_plugins(client: Any, plugin_root: Path) -> AsyncIterator[PluginManager]:
    """Convenience lifecycle context for tests and future bootstrap wiring."""
    manager = PluginManager(client, plugin_root)
    await manager.load_all()
    try:
        yield manager
    finally:
        await manager.shutdown()
