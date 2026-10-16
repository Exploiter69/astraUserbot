"""Generated-plugin end-to-end acceptance for PluginHarness."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from astra.sdk_generator import create_plugin
from astra.testing import PluginHarness
from core.registry import list_registrations


def _modules_under(root: Path) -> set[str]:
    found = set()
    for name, module in tuple(sys.modules.items()):
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if not origin:
            origin = getattr(module, "__file__", None)
        if not origin or origin in {"built-in", "frozen"}:
            continue
        try:
            Path(origin).resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        found.add(name)
    return found


async def _run_generated_plugin(project_root: Path, *, first: bool) -> None:
    generated = create_plugin("harness_generated", project_root=project_root)
    plugin_root = generated.parent
    before_ids = {item.registration_id for item in list_registrations()}

    async with PluginHarness(
        plugin_root=plugin_root,
        project_root=project_root,
    ) as harness:
        assert harness.manager is not None
        record = harness.manager.records["plugins.harness_generated.plugin"]
        assert record.state.value == "RUNNING"
        assert len(record.registrations) == 1

        result = await harness.emit_command(".harness-generated-info")
        assert result.matched is True
        assert [effect.operation for effect in result.effects] == ["event.respond"]
        assert [effect.args for effect in result.effects] == [
            (
                "harness_generated is a generated plugin scaffold. Replace this command "
                "with your plugin's real behavior.",
            )
        ]
        assert harness.calls == harness.effects

        if first:
            await harness.storage.execute(
                "CREATE TABLE harness_e2e_rows (value TEXT PRIMARY KEY)"
            )
            await harness.storage.execute(
                "INSERT INTO harness_e2e_rows(value) VALUES (?)",
                ("first-harness-only",),
            )
            assert (await harness.storage.fetchone(
                "SELECT value FROM harness_e2e_rows"
            ))[0] == "first-harness-only"
        else:
            assert await harness.storage.fetchone(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='harness_e2e_rows'"
            ) is None

    assert {item.registration_id for item in list_registrations()} == before_ids
    assert _modules_under(project_root) == set()


def test_generated_plugin_dispatch_and_second_harness_are_isolated(tmp_path: Path) -> None:
    first_root = tmp_path / "first-generated-project"
    second_root = tmp_path / "second-generated-project"
    try:
        import asyncio

        asyncio.run(_run_generated_plugin(first_root, first=True))
        asyncio.run(_run_generated_plugin(second_root, first=False))
    finally:
        if first_root.exists():
            shutil.rmtree(first_root)
        if second_root.exists():
            shutil.rmtree(second_root)
