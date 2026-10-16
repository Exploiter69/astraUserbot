"""Lifecycle contract tests for the Phase 5b PluginHarness."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from astra.testing import PluginHarness
from core.context import get_application_context
from core.registry import list_registrations


def _write_plugin(project_root: Path, package: str, source: str) -> Path:
    plugin_dir = project_root / "plugins" / package
    plugin_dir.mkdir(parents=True)
    (project_root / "plugins" / "__init__.py").touch()
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(source, encoding="utf-8")
    return project_root / "plugins"


def _basic_plugin(package: str, setup_body: str) -> str:
    return f'''"""Harness fixture plugin."""
plugin_name = "plugins.{package}.plugin"
plugin_version = "1.0.0"
plugin_api_version = 1
dependencies = ()
optional_dependencies = ()
capabilities = ()
description = "PluginHarness lifecycle fixture."
critical = False

def setup(client):
{setup_body}
'''


def test_harness_boots_real_storage_without_worker_or_credentials(tmp_path: Path) -> None:
    plugin_root = tmp_path / "empty-plugins"
    plugin_root.mkdir()
    (plugin_root / "__init__.py").touch()
    before_context = get_application_context()

    async def run() -> None:
        async with PluginHarness(plugin_root=plugin_root) as harness:
            assert harness.context.get("storage") is harness.storage
            assert harness.context.get("jobs") is harness.jobs
            assert harness.storage._started is True
            assert harness.storage.conn is not None
            migrations = await harness.storage.fetchall(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
            assert [row[0] for row in migrations] == list(range(1, 15))
            assert harness.jobs._worker_task is None
            assert harness.jobs._started is False
            assert harness.telegram.handlers == []
            with pytest.raises(RuntimeError, match="network disabled"):
                await harness.context.get("http").get("https://example.com")
    asyncio.run(run())
    assert get_application_context() is before_context


def test_harness_storage_instances_are_isolated(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_plugins = first_root / "plugins"
    second_plugins = second_root / "plugins"
    first_plugins.mkdir(parents=True)
    second_plugins.mkdir(parents=True)
    (first_plugins / "__init__.py").touch()
    (second_plugins / "__init__.py").touch()

    async def seed(storage) -> None:
        await storage.execute(
            "CREATE TABLE IF NOT EXISTS harness_rows (value TEXT PRIMARY KEY)"
        )
        await storage.execute("INSERT INTO harness_rows(value) VALUES (?)", ("first",))

    async def run() -> None:
        async with PluginHarness(
            plugin_root=first_plugins, project_root=first_root, seed=seed
        ) as first:
            first_path = first.storage.path
            assert (await first.storage.fetchone(
                "SELECT value FROM harness_rows"
            ))[0] == "first"
        async with PluginHarness(
            plugin_root=second_plugins, project_root=second_root
        ) as second:
            assert second.storage.path != first_path
            assert await second.storage.fetchone(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='harness_rows'"
            ) is None
    asyncio.run(run())


def test_harness_restores_globals_and_removes_owned_temp_root(tmp_path: Path) -> None:
    plugin_root = tmp_path / "empty-plugins"
    plugin_root.mkdir()
    (plugin_root / "__init__.py").touch()
    before_context = get_application_context()
    before_ids = {item.registration_id for item in list_registrations()}
    before_modules = set(sys.modules)

    async def run() -> Path:
        async with PluginHarness(plugin_root=plugin_root) as harness:
            owned_root = harness.project_root
            assert owned_root.exists()
            assert get_application_context() is harness.context
            assert {item.registration_id for item in list_registrations()} == before_ids
            return owned_root

    owned_root = asyncio.run(run())
    assert get_application_context() is before_context
    assert not owned_root.exists()
    assert {item.registration_id for item in list_registrations()} == before_ids
    leaked = []
    for name in set(sys.modules) - before_modules:
        module = sys.modules.get(name)
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if origin and Path(origin).exists() and (
            str(origin).startswith(str(owned_root))
        ):
            leaked.append(name)
    assert leaked == []


def test_plugin_setup_failure_unwinds_journal_and_restores_context(tmp_path: Path) -> None:
    project_root = tmp_path / "failed-project"
    plugin_root = _write_plugin(
        project_root,
        "failure_fixture",
        _basic_plugin(
            "failure_fixture",
            """    from pathlib import Path
    from astra.sdk import register_command, tracked_resource
    def cleanup(resource):
        resource["cleaned"] = True
        Path(__file__).resolve().parents[2].joinpath("cleanup.txt").write_text("cleaned", encoding="utf-8")
    resource = tracked_resource(
        lambda: {"cleaned": False}, cleanup, kind="fixture",
        identity="failure-fixture-resource",
    )
    async def handler(event):
        await event.edit("should never dispatch")
    register_command(client, r"^\\.harness-failure$", handler, category="test")
    raise RuntimeError("intentional setup failure")""",
        ),
    )
    before_context = get_application_context()
    before_ids = {item.registration_id for item in list_registrations()}
    before_modules = set(sys.modules)

    async def run() -> None:
        with pytest.raises(Exception, match="intentional setup failure"):
            async with PluginHarness(
                plugin_root=plugin_root, project_root=project_root
            ):
                pytest.fail("a plugin setup failure must fail harness entry")

    asyncio.run(run())
    assert get_application_context() is before_context
    assert {item.registration_id for item in list_registrations()} == before_ids
    assert (project_root / "cleanup.txt").read_text(encoding="utf-8") == "cleaned"
    leaked = []
    for name in set(sys.modules) - before_modules:
        module = sys.modules.get(name)
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if origin and Path(origin).resolve().is_relative_to(project_root.resolve()):
            leaked.append(name)
    assert leaked == []


def test_network_policy_can_opt_in_to_loopback_only(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    (plugin_root / "__init__.py").touch()

    async def run() -> None:
        async with PluginHarness(
            plugin_root=plugin_root,
            project_root=tmp_path / "project",
            network_policy="loopback",
        ) as harness:
            with pytest.raises(RuntimeError, match="network disabled"):
                await harness.context.get("http").get("https://example.com")
            # A loopback URL is permitted by policy; an unused port fails locally.
            with pytest.raises(Exception):
                await harness.context.get("http").get(
                    "http://127.0.0.1:1/", retries=0, timeout=0.1
                )
    asyncio.run(run())
