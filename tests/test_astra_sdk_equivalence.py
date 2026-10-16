"""Behavioral equivalence tests for public SDK and raw-core plugin contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from astra.sdk import register_command
from core.plugins.manager import PluginManager, PluginState
from core.registry import COMMANDS, get_registration, register_cmd
from astra.testing import FakeTelegramClient, PluginHarness


def _write_plugin(plugin_root: Path, module_name: str, *, public_sdk: bool) -> None:
    register_import = (
        "from astra.sdk import register_command as register\n"
        if public_sdk
        else "from core.registry import register_cmd as register\n"
    )
    source = (
        register_import
        + "from core.plugins.capabilities import current_identity\n"
        + f"plugin_name = {module_name!r}\n"
        + "plugin_version = '2.1.0'\n"
        + "plugin_api_version = 1\n"
        + "description = 'Equivalent command plugin'\n"
        + "dependencies = ()\n"
        + "optional_dependencies = ()\n"
        + "capabilities = ('telegram.read',)\n"
        + "critical = False\n"
        + "effects = []\n"
        + "results = []\n"
        + "identities = []\n"
        + "\n"
        + "async def handle(event):\n"
        + "    effects.append('handled')\n"
        + "    identities.append(current_identity())\n"
        + "    results.append('same-result')\n"
        + "    return 'same-result'\n"
        + "\n"
        + "def setup(client):\n"
        + "    register(\n"
        + "        client,\n"
        + "        pattern="
        + repr(r"^\.phase5a-equivalence$")
        + ",\n"
        + "        handler=handle,\n"
        + "        category='test',\n"
        + "        description='Equivalent command',\n"
        + "        aliases=['phase5a-equivalence-alias'],\n"
        + "        permission='owner',\n"
        + "        operation_class='READ',\n"
        + "        required_capabilities=['telegram.read'],\n"
        + "        examples=['.phase5a-equivalence'],\n"
        + "        compatibility='1.0',\n"
        + "        priority=100,\n"
        + "        timeout_seconds=10.0,\n"
        + "        usage='.phase5a-equivalence',\n"
        + "    )\n"
    )
    (plugin_root / f"{module_name.rsplit('.', 1)[-1]}.py").write_text(
        source, encoding="utf-8"
    )


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
    project_root: Path, module_name: str, *, public_sdk: bool
) -> tuple[tuple[object, ...], tuple[object, ...], str, list[str], list[object]]:
    plugin_root = project_root / "plugins"
    plugin_root.mkdir(parents=True, exist_ok=True)
    _write_plugin(plugin_root, module_name, public_sdk=public_sdk)

    async with PluginHarness(plugin_root, project_root=project_root) as harness:
        assert harness.manager is not None
        record = harness.manager.records[module_name]
        assert record.state is PluginState.RUNNING
        assert len(record.registrations) == 1
        registration_id = next(iter(record.registrations))
        registration = get_registration(registration_id)
        before = (
            _metadata_signature(record),
            _command_signature(registration),
            registration.handler,
        )

        dispatch = await harness.emit_command(".phase5a-equivalence")
        assert dispatch.matched
        assert dispatch.event is not None
        assert dispatch.pattern_match is not None
        assert dispatch.handler is registration.wrapper
        assert record.module is not None
        assert record.module.results == ["same-result"]
        assert record.module.effects == ["handled"]

        from core.plugins.capabilities import ExecutionIdentity

        assert record.module.identities == [
            ExecutionIdentity(kind="plugin", name=module_name)
        ]
        assert len(harness.telegram.handlers) == 1

        await harness.manager.unload(module_name)
        assert record.state is PluginState.UNLOADED
        assert not record.registrations
        assert not harness.telegram.handlers
        assert registration.pattern not in COMMANDS

        return (
            before[0],
            before[1],
            record.module.results[0],
            list(record.module.effects),
            list(record.module.identities),
        )


def test_sdk_and_raw_core_plugins_have_equivalent_runtime_behavior(tmp_path: Path) -> None:
    async def run() -> None:
        sdk_name = "plugins.phase5a_sdk_equivalence"
        core_name = "plugins.phase5a_core_equivalence"

        sdk_result = await _load_run_unload(
            tmp_path / "sdk", sdk_name, public_sdk=True
        )
        core_result = await _load_run_unload(
            tmp_path / "core", core_name, public_sdk=False
        )

        assert sdk_result[0] == core_result[0]
        assert sdk_result[1] == core_result[1]
        assert sdk_result[2] == core_result[2] == "same-result"
        assert sdk_result[3] == core_result[3] == ["handled"]
        assert [identity.kind for identity in sdk_result[4]] == [identity.kind for identity in core_result[4]] == ["plugin"]
        assert len(sdk_result[4]) == len(core_result[4]) == 1

    asyncio.run(run())


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
                    # The registry wrapper translates handler exceptions, so assert
                    # the proxy directly for the denied-before-side-effect boundary.
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
                    # No SDK denial or interception occurs on this raw facade path.
                    await registration.wrapper(SimpleNamespace(out=True))
                assert calls == [("chat", "message")]
            finally:
                registration.unregister(client)
        finally:
            await storage.close()

    asyncio.run(run())
