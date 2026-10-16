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
