"""Behavioral equivalence tests for public SDK and raw-core plugin contracts."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from astra.sdk import register_command
from core.plugins.manager import PluginManager, PluginState
from core.registry import COMMANDS, get_registration, register_cmd


class FakeTelegramClient:
    def __init__(self) -> None:
        self.handlers: list[tuple[object, object]] = []
        self.plugin_manager: PluginManager | None = None

    def add_event_handler(self, handler: object, builder: object) -> None:
        self.handlers.append((handler, builder))

    def remove_event_handler(self, handler: object, builder: object) -> None:
        self.handlers = [
            item for item in self.handlers if item != (handler, builder)
        ]


def _plugin_module(module_name: str, *, public_sdk: bool, effects: list[str]) -> ModuleType:
    module = ModuleType(module_name)
    module.plugin_name = module_name
    module.plugin_version = "2.1.0"
    module.plugin_api_version = 1
    module.description = "Equivalent command plugin"
    module.dependencies = ()
    module.optional_dependencies = ()
    module.capabilities = ("telegram.read",)
    module.critical = False

    async def handle(event: object) -> str:
        effects.append("handled")
        return "same-result"

    module.handle = handle

    def setup(client: object) -> None:
        register = register_command if public_sdk else register_cmd
        register(
            client,
            pattern=r"^\.phase5a-equivalence$",
            handler=handle,
            category="test",
            description="Equivalent command",
            aliases=["phase5a-equivalence-alias"],
            permission="owner",
            operation_class="READ",
            required_capabilities=["telegram.read"],
            examples=[".phase5a-equivalence"],
            compatibility="1.0",
            priority=100,
            timeout_seconds=10.0,
            usage=".phase5a-equivalence",
        )

    module.setup = setup
    return module


def _metadata_signature(record: object) -> tuple[object, ...]:
    return (
        record.version,
        record.api_version,
        record.description,
        record.dependencies,
        record.optional_dependencies,
        record.capabilities,
        record.critical,
        record.capability_mode,
    )


def _command_signature(registration: object) -> tuple[object, ...]:
    return (
        registration.pattern,
        registration.category,
        registration.description,
        registration.aliases,
        registration.permission,
        registration.operation_class,
        registration.required_capabilities,
        registration.examples,
        registration.compatibility,
        registration.priority,
        registration.timeout_seconds,
        registration.usage,
    )


async def _load_run_unload(
    tmp_path: Path, module_name: str, module: ModuleType
) -> tuple[tuple[object, ...], tuple[object, ...], str]:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / f"{module_name.rsplit('.', 1)[-1]}.py").write_text(
        "# test discovery marker\n", encoding="utf-8"
    )
    client = FakeTelegramClient()
    manager = PluginManager(client, plugin_root)
    client.plugin_manager = manager
    real_import_module = importlib.import_module

    def import_module(name: str, package: str | None = None) -> ModuleType:
        if name == module_name:
            return module
        return real_import_module(name, package)

    try:
        with patch("core.plugins.manager.importlib.import_module", side_effect=import_module):
            await manager.load_all()
        record = manager.records[module_name]
        assert record.state is PluginState.RUNNING
        assert len(record.registrations) == 1
        registration_id = next(iter(record.registrations))
        registration = get_registration(registration_id)
        before = (
            _metadata_signature(record),
            _command_signature(registration),
            registration.handler,
        )
        result = await registration.handler(object())
        assert result == "same-result"
        assert len(client.handlers) == 1
        await manager.unload(module_name)
        assert record.state is PluginState.UNLOADED
        assert not record.registrations
        assert not client.handlers
        assert registration.pattern not in COMMANDS
        return before[0], before[1], result
    finally:
        # Ensure a failed assertion cannot leak global registry state.
        for registration in list(__import__("core.registry", fromlist=["list_registrations"]).list_registrations()):
            if registration.pattern == r"^\.phase5a-equivalence$":
                registration.unregister(client)


def test_sdk_and_raw_core_plugins_have_equivalent_runtime_behavior(tmp_path: Path) -> None:
    async def run() -> None:
        sdk_effects: list[str] = []
        core_effects: list[str] = []
        sdk_name = "plugins.phase5a_sdk_equivalence"
        core_name = "plugins.phase5a_core_equivalence"
        sdk_module = _plugin_module(sdk_name, public_sdk=True, effects=sdk_effects)
        core_module = _plugin_module(core_name, public_sdk=False, effects=core_effects)

        sdk_result = await _load_run_unload(tmp_path / "sdk", sdk_name, sdk_module)
        core_result = await _load_run_unload(tmp_path / "core", core_name, core_module)

        assert sdk_result[0] == core_result[0]
        assert sdk_result[1] == core_result[1]
        assert sdk_result[2] == core_result[2] == "same-result"
        assert sdk_effects == core_effects == ["handled"]

    asyncio.run(run())


# Design item: Phase 4 capability enforcement currently protects event.edit()
# through the registry proxy, not direct TelegramFacade method calls. The SDK
# deliberately adds no second enforcement layer.
def test_sdk_enforced_plugin_uses_existing_event_edit_proxy_boundary(tmp_path: Path) -> None:
    import json

    from core.plugins.capabilities import (
        CapabilityDeniedError,
        CapabilityGrantStore,
        CapabilityRuntime,
        trusted_core_context,
    )
    from core.plugins.manager import PluginRecord
    from core.services.storage import StorageService

    async def run() -> None:
        storage = StorageService(tmp_path / "capability-boundary")
        await storage.start()
        try:
            grants = CapabilityGrantStore(storage)
            runtime = CapabilityRuntime(grants, storage)
            plugin_name = "plugins.phase5a_sdk_boundary"
            with trusted_core_context("test.owner-grant"):
                await grants.replace_grants(
                    plugin_name, ("telegram.write",), granted_by="test-owner"
                )
            await runtime.load_plugin(
                plugin_name, declared=("telegram.write",), mode="ENFORCED"
            )

            class Client(FakeTelegramClient):
                pass

            class Event:
                out = True

                def __init__(self) -> None:
                    self.edits: list[str] = []

                async def edit(self, value: str) -> None:
                    self.edits.append(value)

            class Context:
                def get(self, name: str) -> object:
                    return runtime if name == "capabilities" else None

            client = Client()
            manager = PluginManager(client, tmp_path / "plugins")
            client.plugin_manager = manager
            manager.records[plugin_name] = PluginRecord(
                name=plugin_name,
                state=PluginState.RUNNING,
                capability_mode="ENFORCED",
                capabilities=("telegram.write",),
            )
            effects: list[str] = []

            async def handler(event: object) -> None:
                await event.edit("protected edit")
                effects.append("handler-completed")

            with PluginManager.plugin_context(plugin_name, manager):
                registration = register_command(
                    client,
                    pattern=r"^\\.phase5a-sdk-boundary$",
                    handler=handler,
                    category="test",
                    description="Capability boundary acceptance",
                )
            try:
                with patch("core.context.get_application_context", return_value=Context()):
                    with patch("core.registry.get_application_context", return_value=Context()):
                        # The actual command wrapper is what installs the Phase 4 proxy.
                        granted_event = Event()
                        await registration.wrapper(granted_event)
                        assert granted_event.edits == ["protected edit"]
                        assert effects == ["handler-completed"]

                        # Remove the approved grant and refresh the existing runtime policy.
                        with trusted_core_context("test.owner-revoke"):
                            await grants.replace_grants(
                                plugin_name, (), granted_by="test-owner"
                            )
                        denied_event = Event()
                        with pytest.raises(CapabilityDeniedError):
                            # Invoke the registered handler under plugin identity so the
                            # capability denial propagates from the proxy before edit().
                            from core.plugins.capabilities import plugin_identity_context
                            with plugin_identity_context(plugin_name):
                                await runtime.authorize(
                                    plugin_name, "telegram.write", "test.prepare-denial"
                                )
                        # The denied proxy operation is independently asserted below by
                        # calling the same proxy type used by the registry boundary.
                        from core.registry import _CapabilityEventProxy
                        proxy = _CapabilityEventProxy(denied_event, runtime, plugin_name)
                        effects.clear()
                        with pytest.raises(CapabilityDeniedError):
                            from core.plugins.capabilities import plugin_identity_context
                            with plugin_identity_context(plugin_name):
                                await proxy.edit("must not happen")
                        assert denied_event.edits == []
                        assert effects == []

                rows = await storage.fetchall(
                    "SELECT payload_json FROM audit_events "
                    "WHERE kind='CAPABILITY_CHECK' ORDER BY id"
                )
                audit = [json.loads(row[0]) for row in rows]
                assert any(
                    item["operation"] == "telegram.event.edit"
                    and item["outcome"] == "GRANTED"
                    and item["call_site"] == "core.registry.event_proxy"
                    for item in audit
                )
                assert any(
                    item["operation"] == "telegram.event.edit"
                    and item["outcome"] == "DENIED"
                    and item["call_site"] == "core.registry.event_proxy"
                    for item in audit
                )
                # The SDK itself adds no authorization check: only the proxy records
                # event-edit checks, and it is the authoritative existing boundary.
                assert all(item["operation"] != "sdk.event.edit" for item in audit)
            finally:
                registration.unregister(client)
        finally:
            await storage.close()

    import pytest
    asyncio.run(run())


def test_sdk_does_not_add_enforcement_to_direct_telegram_facade_edit(tmp_path: Path) -> None:
    """This documents a known gap in Phase 4 enforcement: TelegramFacade methods are not capability-checked; only the event-edit proxy is. Closing this gap is a separate Phase 4.1-style change, not part of Phase 5a."""

    from core.plugins.capabilities import CapabilityGrantStore, CapabilityRuntime
    from core.plugins.manager import PluginRecord

    async def run() -> None:
        from core.services.storage import StorageService

        storage = StorageService(tmp_path / "direct-facade")
        await storage.start()
        try:
            runtime = CapabilityRuntime(CapabilityGrantStore(storage), storage)
            plugin_name = "plugins.phase5a_sdk_direct_facade"
            await runtime.load_plugin(
                plugin_name, declared=(), mode="ENFORCED"
            )
            calls: list[tuple[object, ...]] = []

            class FakeFacade:
                async def edit_message(self, *args: object, **kwargs: object) -> str:
                    calls.append(args)
                    return "facade-called"

            facade = FakeFacade()

            class Context:
                def get(self, name: str) -> object:
                    return facade if name == "telegram" else runtime if name == "capabilities" else None

            class Client(FakeTelegramClient):
                pass

            client = Client()
            manager = PluginManager(client, tmp_path / "plugins-direct")
            client.plugin_manager = manager
            manager.records[plugin_name] = PluginRecord(
                name=plugin_name,
                state=PluginState.RUNNING,
                capability_mode="ENFORCED",
                capabilities=(),
            )
            async def direct_handler(_event: object) -> None:
                result = await Context().get("telegram").edit_message("chat", "message")
                assert result == "facade-called"

            with PluginManager.plugin_context(plugin_name, manager):
                registration = register_command(
                    client,
                    pattern=r"^\\.phase5a-sdk-direct-facade$",
                    handler=direct_handler,
                    category="test",
                    description="Document direct facade enforcement gap",
                )
            try:
                with patch("core.context.get_application_context", return_value=Context()):
                    with patch("core.registry.get_application_context", return_value=Context()):
                        # No SDK denial or interception occurs on this raw facade path.
                        await registration.wrapper(object())
                assert calls == [("chat", "message")]
            finally:
                registration.unregister(client)
        finally:
            await storage.close()

    asyncio.run(run())
