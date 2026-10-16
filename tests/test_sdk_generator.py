"""Acceptance tests for the deterministic Astra SDK plugin generator."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from astra.sdk_generator import create_plugin
from core.plugins.contract import metadata_for
from core.plugins.manager import PluginLifecycleError, PluginManager, PluginState
from core.registry import COMMANDS, list_registrations

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = {
    "__init__.py",
    "plugin.py",
    "README.md",
    "tests/test_plugin.py",
}


class FakeClient:
    """Test harness only; it is never used as a generated plugin's runtime client."""

    def __init__(self) -> None:
        self.handlers: list[tuple[object, object]] = []
        self.plugin_manager: PluginManager | None = None

    def add_event_handler(self, handler: object, builder: object) -> None:
        self.handlers.append((handler, builder))

    def remove_event_handler(self, handler: object, builder: object) -> None:
        self.handlers = [item for item in self.handlers if item != (handler, builder)]


@pytest.mark.parametrize(
    "name",
    [
        "",
        "../escape",
        "Uppercase",
        "has-dash",
        "two words",
        "class",
        "__pycache__",
        "a" * 49,
    ],
)
def test_invalid_name_is_rejected_before_any_file_is_written(
    tmp_path: Path, name: str
) -> None:
    project_root = tmp_path / "must-not-be-created"
    before_ids = {item.registration_id for item in list_registrations()}
    with pytest.raises(ValueError):
        create_plugin(name, project_root=project_root)
    assert not project_root.exists()
    assert {item.registration_id for item in list_registrations()} == before_ids


def test_collision_refuses_overwrite_and_force_replaces_output(tmp_path: Path) -> None:
    output = create_plugin("collision_case", project_root=tmp_path)
    before = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    with pytest.raises(FileExistsError, match="--force"):
        create_plugin("collision_case", project_root=tmp_path)
    after = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert after == before

    (output / "README.md").write_text("modified by test", encoding="utf-8")
    create_plugin("collision_case", project_root=tmp_path, force=True)
    regenerated = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert regenerated == before
    assert set(regenerated) == REQUIRED_FILES


def test_generated_layout_import_and_runtime_normalized_metadata(
    tmp_path: Path,
) -> None:
    output = create_plugin("metadata_case", project_root=tmp_path)
    assert {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    } == REQUIRED_FILES
    assert not list(output.rglob("*manifest*"))

    spec = importlib.util.spec_from_file_location(
        "generated_metadata_case", output / "plugin.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    normalized = metadata_for(module)
    assert normalized.name == "plugins.metadata_case.plugin"
    assert normalized.version == module.plugin_version == "1.0.0"
    assert normalized.api_version == module.plugin_api_version == 1
    assert normalized.description == module.description
    assert normalized.dependencies == module.dependencies == ()
    assert normalized.optional_dependencies == module.optional_dependencies == ()
    assert normalized.capabilities == module.capabilities == ("telegram.read",)
    assert normalized.critical is module.critical is False
    assert callable(module.setup)
    readme = (output / "README.md").read_text(encoding="utf-8")
    assert "declaration is not enforcement" in readme.lower()


def test_generated_plugin_manager_lifecycle_and_test_directory_exclusion(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        output = create_plugin("lifecycle_case", project_root=tmp_path)
        plugin_root = tmp_path / "plugins"
        module_name = "plugins.lifecycle_case.plugin"
        command_pattern = r"^\.lifecycle-case-info$"
        client = FakeClient()
        manager = PluginManager(client, plugin_root)
        client.plugin_manager = manager
        before_ids = {item.registration_id for item in list_registrations()}
        real_import_module = importlib.import_module

        def import_module(name: str, package: str | None = None) -> ModuleType:
            if name == module_name:
                spec = importlib.util.spec_from_file_location(
                    name, output / "plugin.py"
                )
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
            return real_import_module(name, package)

        try:
            assert [item.name for item in manager.discover()] == [module_name]
            with patch(
                "core.plugins.manager.importlib.import_module",
                side_effect=import_module,
            ):
                await manager.load_all()
            record = manager.records[module_name]
            assert record.state is PluginState.RUNNING
            assert record.capabilities == ("telegram.read",)
            assert len(record.registrations) == 1
            registrations = [
                item for item in list_registrations()
                if item.pattern == command_pattern
            ]
            assert len(registrations) == 1
            assert registrations[0].registration_id in record.registrations
            assert len(client.handlers) == 1

            await manager.unload(module_name)
            assert record.state is PluginState.UNLOADED
            assert not record.registrations
            assert not client.handlers
            assert command_pattern not in COMMANDS
        finally:
            for registration in list_registrations():
                if registration.registration_id not in before_ids:
                    registration.unregister(client)

    asyncio.run(run())


def test_generated_acceptance_test_passes_without_telegram_credentials(
    tmp_path: Path,
) -> None:
    output = create_plugin("subprocess_case", project_root=tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    for key in list(env):
        if key.upper() in {"API_ID", "API_HASH", "BOT_TOKEN", "SESSION_STRING"} or key.upper().startswith("TELEGRAM_"):
            env.pop(key)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(output / "tests" / "test_plugin.py"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "1 passed" in result.stdout


def test_cli_entry_point_creates_plugin_from_working_directory(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "astra.sdk_generator",
            "create-plugin",
            "cli_case",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert (tmp_path / "plugins" / "cli_case" / "plugin.py").is_file()
    assert "plugins/cli_case" in result.stdout.replace("\\", "/")


def test_failed_generated_setup_rolls_back_global_registration_state(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        output = create_plugin("failure_case", project_root=tmp_path)
        module_name = "plugins.failure_case.plugin"
        command_pattern = r"^\.failure-case-info$"
        client = FakeClient()
        manager = PluginManager(client, tmp_path / "plugins")
        client.plugin_manager = manager
        before_ids = {item.registration_id for item in list_registrations()}
        real_import_module = importlib.import_module

        def import_module(name: str, package: str | None = None) -> ModuleType:
            if name == module_name:
                spec = importlib.util.spec_from_file_location(
                    name, output / "plugin.py"
                )
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                real_setup = module.setup

                def failing_setup(runtime_client: object) -> None:
                    real_setup(runtime_client)
                    raise RuntimeError("intentional setup failure for rollback test")

                module.setup = failing_setup
                return module
            return real_import_module(name, package)

        try:
            assert [item.name for item in manager.discover()] == [module_name]
            with patch(
                "core.plugins.manager.importlib.import_module",
                side_effect=import_module,
            ):
                with pytest.raises(PluginLifecycleError, match="intentional setup failure"):
                    await manager.enable_plugin(module_name)
            assert manager.records[module_name].state is PluginState.FAILED_SETUP
            assert not manager.records[module_name].registrations
            assert not client.handlers
            assert command_pattern not in COMMANDS
            assert {item.registration_id for item in list_registrations()} == before_ids
        finally:
            for registration in list_registrations():
                if registration.registration_id not in before_ids:
                    registration.unregister(client)

    asyncio.run(run())
