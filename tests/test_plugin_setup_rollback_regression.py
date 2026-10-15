"""Regression coverage for plugin setup side effects that outlive failed setup."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import types
from pathlib import Path

import pytest

from core.plugins.manager import PluginLifecycleError, PluginManager, PluginRecord
from core.registry import COMMANDS, _REGISTRATIONS, register_cmd
from core.services.jobs import JobEngine, JobState
from core.services.storage import StorageService
from core.tasks import TaskSupervisor


class FakeClient:
    def __init__(self):
        self.handlers = []

    def add_event_handler(self, callback, builder=None):
        self.handlers.append((callback, builder))

    def remove_event_handler(self, callback, builder=None):
        try:
            self.handlers.remove((callback, builder))
        except ValueError:
            pass


@pytest.mark.parametrize(
    ("stage", "expected_unwound"),
    [
        ("setup_started", ("commands", "tasks", "jobs", "resource")),
        ("command_registered", ("commands", "tasks", "jobs", "resource")),
        pytest.param(
            "task_scheduled",
            ("commands", "tasks", "jobs", "resource"),
            marks=pytest.mark.xfail(
                strict=True,
                reason="Current plugin rollback removes command registrations only; it does not cancel setup-created TaskSupervisor tasks.",
            ),
        ),
        pytest.param(
            "job_queued",
            ("commands", "tasks", "jobs", "resource"),
            marks=pytest.mark.xfail(
                strict=True,
                reason="Current plugin rollback has no setup side-effect journal and leaves queued durable jobs behind.",
            ),
        ),
        pytest.param(
            "resource_created",
            ("commands", "tasks", "jobs", "resource"),
            marks=pytest.mark.xfail(
                strict=True,
                reason="Current plugin rollback cannot unwind arbitrary resources created during setup.",
            ),
        ),
    ],
)
@pytest.mark.asyncio
async def test_failed_setup_unwinds_every_side_effect(stage, expected_unwound):
    """Each setup failure stage must leave no command, task, job, or resource."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        storage = StorageService(root / "state")
        await storage.start()
        jobs = JobEngine(storage, worker_id=f"phase1-{stage}")
        tasks = TaskSupervisor()
        resource_db = root / "plugin-resource.sqlite3"
        plugin_name = f"plugins.phase1_rollback_{stage}"
        command_pattern = rf"^\.p1rb{stage}($|\s)"
        queued_job = None
        scheduled_task = None

        module = types.ModuleType(plugin_name)

        async def setup(_client):
            nonlocal queued_job, scheduled_task
            if stage == "setup_started":
                raise RuntimeError("synthetic setup failure")

            register_cmd(
                client,
                command_pattern,
                lambda _event: None,
                description="Phase 1 rollback regression test",
            )
            if stage == "command_registered":
                raise RuntimeError("synthetic setup failure after command registration")

            scheduled_task = tasks.create_task(
                asyncio.Event().wait(),
                name=f"phase1-{stage}",
                owner=plugin_name,
            )
            if stage == "task_scheduled":
                raise RuntimeError("synthetic setup failure after scheduling")

            queued_job = await jobs.enqueue("PHASE1_FAKE_EXTERNAL_EFFECT", {"stage": stage})
            if stage == "job_queued":
                raise RuntimeError("synthetic setup failure after queueing")

            with sqlite3.connect(resource_db) as conn:
                conn.execute("CREATE TABLE plugin_owned_resource (value TEXT)")
                conn.execute("INSERT INTO plugin_owned_resource(value) VALUES ('created')")
            raise RuntimeError("synthetic setup failure after resource creation")

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        # Production loader installs this reference so register_cmd can record
        # ownership and enable_plugin can unwind setup-created registrations.
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        try:
            with pytest.raises(PluginLifecycleError, match="Enable failed"):
                await manager.enable_plugin(plugin_name)

            # Registration rollback is already implemented and is the baseline
            # expected behavior for the first two stages.
            owned_patterns = [
                pattern for pattern, value in COMMANDS.items()
                if value.get("registration_id") in manager.get(plugin_name).registrations
            ]
            assert not owned_patterns
            assert not any(
                registration.owner == plugin_name
                for registration in _REGISTRATIONS.values()
            )

            # Check effects in reverse creation order so each parametrized
            # failure demonstrates the side effect introduced at that stage.
            if "resource" in expected_unwound and resource_db.exists():
                with sqlite3.connect(resource_db) as conn:
                    tables = {
                        row[0] for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                assert "plugin_owned_resource" not in tables, (
                    "failed plugin setup leaked its SQLite resource"
                )

            if "jobs" in expected_unwound and queued_job is not None:
                current = await jobs.get(queued_job.id)
                assert current.state == JobState.CANCELLED, (
                    "failed plugin setup leaked a queued durable job "
                    f"in state {current.state.value}"
                )

            if "tasks" in expected_unwound:
                assert not [
                    item for item in tasks.active()
                    if item.owner == plugin_name
                ], "failed plugin setup leaked a supervised task"

        finally:
            # Test-owned cleanup prevents intentionally observed leaks from
            # contaminating the test process; this is not plugin rollback.
            if scheduled_task is not None and not scheduled_task.done():
                scheduled_task.cancel()
                await asyncio.gather(scheduled_task, return_exceptions=True)
            await tasks.shutdown(timeout=0.01)
            if queued_job is not None:
                try:
                    await jobs.cancel(queued_job.id)
                except (KeyError, ValueError):
                    pass
            await storage.close()
            for registration in list(_REGISTRATIONS.values()):
                if registration.owner == plugin_name:
                    registration.unregister(client)
