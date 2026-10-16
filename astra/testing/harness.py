"""Isolated lifecycle harness for real Astra plugin-runtime components.

This module is test-only. It deliberately does not add seams to production
ApplicationContext, PluginManager, JobEngine, StorageService, or the registry.
"""

from __future__ import annotations

import inspect
import ipaddress
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from astra.testing.context import HarnessApplicationContext
from astra.testing.telegram import FakeTelegramClient, RecordedEffect, emit_command
from core.context import get_application_context, set_application_context
from core.plugins.capabilities import trusted_core_context
from core.plugins.manager import PluginManager, PluginState
from core.registry import list_registrations
from core.services.http import HttpService


class _NetworkPolicyHttpService:
    """Test-only network guard around an HTTP service selected by the harness."""

    def __init__(self, delegate: Any, policy: Any = None) -> None:
        if policy is not None and policy != "loopback" and not callable(policy):
            raise ValueError(
                "network_policy must be None, 'loopback', or a callable accepting a URL"
            )
        self._delegate = delegate
        self._policy = policy

    async def start(self) -> Any:
        starter = getattr(self._delegate, "start", None)
        if starter is None:
            return None
        result = starter()
        return await result if inspect.isawaitable(result) else result

    async def close(self) -> Any:
        closer = getattr(self._delegate, "close", None)
        if closer is None:
            return None
        result = closer()
        return await result if inspect.isawaitable(result) else result

    def _allowed(self, url: str) -> Any:
        if self._policy is None:
            return False
        if self._policy == "loopback":
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            if host == "localhost":
                return True
            try:
                return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
            except ValueError:
                return False
        return self._policy(url)

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        allowed = self._allowed(url)
        if inspect.isawaitable(allowed):
            allowed = await allowed
        if not allowed:
            raise RuntimeError(f"network disabled by PluginHarness: {url}")
        # Do not let a permitted loopback URL redirect a request to an external host.
        if self._policy == "loopback":
            kwargs["allow_redirects"] = False
        request = getattr(self._delegate, "request", None)
        if request is None:
            raise TypeError("HTTP service override must implement request()")
        result = request(method, url, **kwargs)
        return await result if inspect.isawaitable(result) else result

    async def get(self, url: str, **kwargs: Any) -> Any:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self.request("POST", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> Any:
        return await self.request("HEAD", url, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


class PluginHarness:
    """Boot and tear down an isolated plugin runtime without Telegram credentials.

    The optional seed callback receives the real storage service after migrations.
    The optional capability policy callback receives this harness after plugin
    metadata is read and before plugin setup. It may use the real capability
    grant store inside the harness-provided trusted setup scope. Both callbacks
    may be synchronous or asynchronous.

    network_policy defaults to denying every HTTP request. Use "loopback" to
    allow localhost/loopback IPs only, or provide a callable accepting a URL.
    """

    def __init__(
        self,
        plugin_root: str | Path,
        project_root: str | Path | None = None,
        service_overrides: Mapping[str, Any] | None = None,
        seed: Callable[[Any], Any] | None = None,
        capability_policy: Callable[["PluginHarness"], Any] | None = None,
        network_policy: Any = None,
        start_job_worker: bool = False,
    ) -> None:
        if not isinstance(start_job_worker, bool):
            raise TypeError("start_job_worker must be a boolean")
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        if project_root is None:
            self._temporary_directory = tempfile.TemporaryDirectory(
                prefix="astra-plugin-harness-"
            )
            self.project_root = Path(self._temporary_directory.name).resolve()
            self._owns_project_root = True
        else:
            self.project_root = Path(project_root).resolve()
            self.project_root.mkdir(parents=True, exist_ok=True)
            self._owns_project_root = False

        raw_plugin_root = Path(plugin_root)
        self.plugin_root = (
            raw_plugin_root.resolve()
            if raw_plugin_root.is_absolute()
            else (self.project_root / raw_plugin_root).resolve()
        )
        self.service_overrides = dict(service_overrides or {})
        forbidden_overrides = {"storage", "jobs"} & self.service_overrides.keys()
        if forbidden_overrides:
            names = ", ".join(sorted(forbidden_overrides))
            raise ValueError(f"PluginHarness requires real service(s): {names}")
        self.seed_callback = seed
        self.capability_policy = capability_policy
        self.network_policy = network_policy
        self.start_job_worker = start_job_worker

        self.context: HarnessApplicationContext | None = None
        self.manager: PluginManager | None = None
        self.telegram = FakeTelegramClient()
        self.storage: Any = None
        self.jobs: Any = None

        self._started = False
        self._closing = False
        self._closed = False
        self._previous_context: Any = None
        self._registry_snapshot: set[str] = set()
        self._module_snapshot: set[str] = set()
        self._sys_path_entry: str | None = None
        self._plugins_module: Any = None
        self._plugins_original_path: Any = None
        self._plugins_original_search_locations: Any = None
        self._created_package_init: Path | None = None

    @property
    def effects(self) -> tuple[RecordedEffect, ...]:
        return self.telegram.effects

    @property
    def calls(self) -> tuple[RecordedEffect, ...]:
        """Alias for the fake Telegram effect log."""
        return self.effects

    async def __aenter__(self) -> "PluginHarness":
        try:
            await self.start()
        except Exception as start_error:
            try:
                await self.close()
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "PluginHarness startup and cleanup failed",
                    [start_error, cleanup_error],
                ) from start_error
            raise
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            await self.close()
        except Exception as cleanup_error:
            if exc is not None:
                raise ExceptionGroup(
                    "PluginHarness body and cleanup failed",
                    [exc, cleanup_error],
                ) from exc
            raise
        return False

    async def _call(self, callback: Callable[..., Any], *args: Any) -> Any:
        result = callback(*args)
        return await result if inspect.isawaitable(result) else result

    def _prepare_import_path(self) -> None:
        import_root = str(self.plugin_root.parent.resolve())
        if import_root not in sys.path:
            sys.path.insert(0, import_root)
            self._sys_path_entry = import_root

        # Extend a pre-imported repository package rather than evicting it.
        if self.plugin_root.name == "plugins" and self.plugin_root.is_dir():
            existing = sys.modules.get("plugins")
            if existing is not None and hasattr(existing, "__path__"):
                self._plugins_module = existing
                self._plugins_original_path = existing.__path__
                self._plugins_original_search_locations = getattr(
                    getattr(existing, "__spec__", None),
                    "submodule_search_locations",
                    None,
                )
                paths = [str(self.plugin_root)]
                paths.extend(
                    path for path in list(existing.__path__) if path not in paths
                )
                existing.__path__ = paths
                if getattr(existing, "__spec__", None) is not None:
                    existing.__spec__.submodule_search_locations = paths
            else:
                init_file = self.plugin_root / "__init__.py"
                if not init_file.exists():
                    init_file.touch()
                    self._created_package_init = init_file

    def _restore_import_path(self) -> None:
        if self._plugins_module is not None:
            self._plugins_module.__path__ = self._plugins_original_path
            spec = getattr(self._plugins_module, "__spec__", None)
            if spec is not None:
                spec.submodule_search_locations = (
                    self._plugins_original_search_locations
                )
            self._plugins_module = None
        if self._sys_path_entry is not None:
            try:
                sys.path.remove(self._sys_path_entry)
            except ValueError:
                pass
            self._sys_path_entry = None

    def _module_is_harness_owned(self, module: Any) -> bool:
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None) or getattr(module, "__file__", None)
        if not origin or origin in {"built-in", "frozen"}:
            return False
        try:
            Path(origin).resolve().relative_to(self.project_root)
            return True
        except (OSError, ValueError):
            return False

    async def start(self) -> "PluginHarness":
        if self._closed or self._closing:
            raise RuntimeError("PluginHarness is already closed")
        if self._started:
            return self

        self._previous_context = get_application_context()
        self._registry_snapshot = {
            item.registration_id for item in list_registrations()
        }
        self._module_snapshot = set(sys.modules)
        try:
            self.plugin_root.parent.mkdir(parents=True, exist_ok=True)
            self._prepare_import_path()

            # Install the guard before dependent services are constructed.
            overrides = dict(self.service_overrides)
            http_delegate = overrides.get("http")
            if http_delegate is None:
                http_delegate = HttpService()
            overrides["http"] = _NetworkPolicyHttpService(
                http_delegate, self.network_policy
            )
            self.context = HarnessApplicationContext(
                self.telegram,
                self.project_root,
                service_overrides=overrides,
            )
            self.storage = self.context.get("storage")
            self.jobs = self.context.get("jobs")

            # ApplicationContext.start() starts every service, including the
            # JobEngine worker. Start only the real storage service by default.
            await self.storage.start()
            if self.seed_callback is not None:
                with trusted_core_context("plugin_harness.seed"):
                    await self._call(self.seed_callback, self.storage)

            set_application_context(self.context)
            if self.start_job_worker:
                await self.jobs.start()

            self.manager = PluginManager(self.telegram, self.plugin_root)
            self.telegram.plugin_manager = self.manager
            discovered = self.manager.discover()

            # Read metadata first so dependency order is known before setup.
            # Each setup runs through enable_plugin(), which owns the Phase 3c journal.
            for record in discovered:
                record.module = importlib.import_module(record.name)
                record.state = PluginState.LOADED
                self.manager._read_metadata(record)
            order = self.manager._dependency_order()
            self.manager._load_order = list(order)

            if self.capability_policy is not None:
                with trusted_core_context("plugin_harness.capability_policy"):
                    await self._call(self.capability_policy, self)

            for name in order:
                record = self.manager.records[name]
                record.state = PluginState.DISCOVERED
                await self.manager.enable_plugin(name)

            self._started = True
            return self
        except Exception as start_error:
            try:
                await self.close()
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "PluginHarness startup and cleanup failed",
                    [start_error, cleanup_error],
                ) from start_error
            raise

    async def emit_command(self, text: str, **kwargs: Any) -> Any:
        if not self._started or self._closed:
            raise RuntimeError("PluginHarness must be started before dispatch")
        return await emit_command(self.telegram, text, **kwargs)

    async def close(self) -> None:
        if self._closed or self._closing:
            return
        self._closing = True
        errors: list[Exception] = []

        if self.manager is not None:
            try:
                await self.manager.shutdown()
            except Exception as exc:
                errors.append(exc)
            for record in self.manager.records.values():
                if record.state == PluginState.RUNNING:
                    errors.append(
                        RuntimeError(
                            f"Plugin remained RUNNING after manager shutdown: {record.name}"
                        )
                    )
            journal = self.manager.last_failed_setup_journal
            if journal is not None and journal.cleanup_errors:
                errors.append(
                    RuntimeError(
                        "Plugin setup journal cleanup failed: "
                        + "; ".join(journal.cleanup_errors)
                    )
                )

        # Cancel the real TaskSupervisor, then sweep every service to close
        # lazily-opened handles as well as services started explicitly by plugins.
        if self.context is not None:
            try:
                await self.context.close()
            except Exception as exc:
                errors.append(exc)
            for name, service in reversed(tuple(self.context.services.items())):
                closer = getattr(service, "close", None)
                if closer is None:
                    continue
                try:
                    result = closer()
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:
                    errors.append(
                        RuntimeError(
                            f"Failed to close harness service {name}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    )

        set_application_context(self._previous_context)

        for registration in list(list_registrations()):
            if registration.registration_id in self._registry_snapshot:
                continue
            try:
                registration.unregister(self.telegram)
            except Exception as exc:
                errors.append(
                    RuntimeError(
                        f"Failed to remove harness registration "
                        f"{registration.registration_id}: {exc}"
                    )
                )

        for name in sorted(set(sys.modules) - self._module_snapshot, reverse=True):
            module = sys.modules.get(name)
            if module is not None and self._module_is_harness_owned(module):
                sys.modules.pop(name, None)

        self._restore_import_path()
        if self._created_package_init is not None:
            try:
                self._created_package_init.unlink(missing_ok=True)
            except Exception as exc:
                errors.append(exc)
            self._created_package_init = None

        if self._temporary_directory is not None:
            try:
                self._temporary_directory.cleanup()
            except Exception as exc:
                errors.append(exc)
            self._temporary_directory = None

        self._started = False
        self._closed = True
        self._closing = False
        if errors:
            raise ExceptionGroup("PluginHarness cleanup failed", errors)
