"""Regression coverage for plugin setup side effects that outlive failed setup."""

from __future__ import annotations

import asyncio
import inspect
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
        ("task_scheduled", ("commands", "tasks", "jobs", "resource")),
        ("job_queued", ("commands", "tasks", "jobs", "resource")),
        ("resource_created", ("commands", "tasks", "jobs", "resource")),
    ],
)
@pytest.mark.asyncio
async def test_failed_setup_unwinds_every_side_effect(stage, expected_unwound):
    """Each setup failure stage leaves no side effects and unwinds tracked work in reverse."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        storage = StorageService(root / "state")
        await storage.start()
        jobs = JobEngine(storage, worker_id=f"phase3c-step3-{stage}")
        tasks = TaskSupervisor()
        resource_db = root / "plugin-resource.sqlite3"
        plugin_name = f"plugins.phase1_rollback_{stage}"
        command_pattern = rf"^\.p1rb{stage}($|\s)"
        queued_job = None
        scheduled_task = None
        cleanup_order = []
        observed = {}
        module = types.ModuleType(plugin_name)

        def registration_still_exists():
            return any(
                registration.owner == plugin_name
                for registration in _REGISTRATIONS.values()
            )

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

            manager = PluginManager.current_manager()
            assert manager is not None

            def cleanup_sentinel(_resource):
                assert registration_still_exists(), (
                    "command registration must be rolled back after tracked resources"
                )
                cleanup_order.append("sentinel")

            manager.tracked_resource(
                lambda: "sentinel",
                cleanup_sentinel,
                kind="test_resource",
                identity="sentinel",
            )

            scheduled_task = manager.tracked_task(
                tasks,
                asyncio.Event().wait(),
                name=f"phase3c-step3-{stage}",
            )
            if stage == "task_scheduled":
                raise RuntimeError("synthetic setup failure after scheduling")

            queued_job = await manager.tracked_job(
                jobs,
                "PHASE3C_STEP3_ROLLBACK",
                {"stage": stage},
            )
            if stage == "job_queued":
                raise RuntimeError("synthetic setup failure after queueing")

            def create_resource():
                with sqlite3.connect(resource_db) as conn:
                    conn.execute(
                        "CREATE TABLE plugin_owned_resource (value TEXT)"
                    )
                    conn.execute(
                        "INSERT INTO plugin_owned_resource(value) VALUES ('created')"
                    )
                return resource_db

            def cleanup_resource(path):
                assert registration_still_exists(), (
                    "command registration must be rolled back after tracked resources"
                )
                with sqlite3.connect(path) as conn:
                    conn.execute("DROP TABLE plugin_owned_resource")
                cleanup_order.append("resource")

            manager.tracked_resource(
                create_resource,
                cleanup_resource,
                kind="sqlite_resource",
                identity="plugin-owned-sqlite",
            )
            raise RuntimeError("synthetic setup failure after resource creation")

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        # register_cmd uses this reference to record ownership for final rollback.
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        try:
            with pytest.raises(PluginLifecycleError, match="Enable failed"):
                await manager.enable_plugin(plugin_name)

            # The existing setup_started and command_registered contracts remain
            # unchanged: no leaked registrations after a setup failure.
            owned_patterns = [
                pattern for pattern, value in COMMANDS.items()
                if value.get("registration_id") in manager.get(plugin_name).registrations
            ]
            assert not owned_patterns
            assert not registration_still_exists()

            # Check concrete effects and journal order, not merely cleanup callbacks.
            if "resource" in expected_unwound and resource_db.exists():
                with sqlite3.connect(resource_db) as conn:
                    tables = {
                        row[0] for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                if stage == "resource_created":
                    assert "plugin_owned_resource" not in tables, (
                        "failed plugin setup leaked its SQLite resource"
                    )
                else:
                    assert "plugin_owned_resource" not in tables

            if "jobs" in expected_unwound and queued_job is not None:
                current = await jobs.get(queued_job.id)
                assert current.state == JobState.CANCELLED, (
                    "failed plugin setup leaked a queued durable job "
                    f"in state {current.state.value}"
                )
                assert await jobs.claim(("PHASE3C_STEP3_ROLLBACK",)) is None

            if "tasks" in expected_unwound and scheduled_task is not None:
                assert scheduled_task.done(), "tracked task was not awaited during rollback"
                assert scheduled_task.cancelled(), "tracked task was not cancelled during rollback"
                assert not [
                    item for item in tasks.active()
                    if item.owner == plugin_name
                ], "failed plugin setup leaked a supervised task"

            journal = manager.last_failed_setup_journal
            assert journal is not None
            if stage in {"task_scheduled", "job_queued", "resource_created"}:
                expected_kinds = {
                    "task_scheduled": ["task", "test_resource"],
                    "job_queued": ["job", "task", "test_resource"],
                    "resource_created": [
                        "sqlite_resource", "job", "task", "test_resource"
                    ],
                }[stage]
                assert [entry.kind for entry in journal.failure_entries] == expected_kinds
                assert all(
                    entry.cleanup_state == "SUCCEEDED"
                    for entry in journal.failure_entries
                )

                expected_cleanup_order = {
                    "task_scheduled": ["sentinel"],
                    "job_queued": ["sentinel"],
                    "resource_created": ["resource", "sentinel"],
                }[stage]
                assert cleanup_order == expected_cleanup_order
                # Every tracked cleanup asserts the command is still registered;
                # its absence above proves registration rollback runs last.
                assert not registration_still_exists()

        finally:
            # Test-owned cleanup is only a safety net; assertions above verify
            # that plugin rollback itself handled the side effects.
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


@pytest.mark.asyncio
async def test_setup_tracking_api_records_entries_in_attempt_order_and_discards_on_success():
    """The unchanged setup(client) API records tracked resources in its own journal."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        storage = StorageService(root / "state")
        await storage.start()
        jobs = JobEngine(storage, worker_id="phase3c-step1-record")
        tasks = TaskSupervisor()
        plugin_name = "plugins.phase3c_step1_record"
        cleanup_calls = []
        resource = object()
        observed = {}
        module = types.ModuleType(plugin_name)

        async def setup(_client):
            manager = PluginManager.current_manager()
            assert manager is not None
            observed["signature_parameters"] = len(
                inspect.signature(setup).parameters
            )
            scheduled_task = manager.tracked_task(
                tasks,
                asyncio.Event().wait(),
                name="phase3c-step1-task",
            )
            queued_job = await manager.tracked_job(
                jobs,
                "PHASE3C_STEP1_TEST",
                {"plugin": plugin_name},
            )
            created_resource = manager.tracked_resource(
                lambda: resource,
                lambda value: cleanup_calls.append(value),
                kind="test_resource",
                identity="resource-1",
            )
            journal = manager.current_setup_journal()
            assert journal is not None
            observed["journal"] = journal
            observed["entries"] = list(journal.entries)
            observed["task"] = scheduled_task
            observed["job"] = queued_job
            observed["resource"] = created_resource

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        try:
            await manager.enable_plugin(plugin_name)
            entries = observed["entries"]
            assert [entry.kind for entry in entries] == [
                "task", "job", "test_resource"
            ]
            assert [entry.sequence for entry in entries] == [1, 2, 3]
            assert all(entry.plugin_name == plugin_name for entry in entries)
            assert all(
                entry.attempt_id == observed["journal"].attempt_id
                for entry in entries
            )
            assert entries[0].identity
            assert entries[1].identity == observed["job"].id
            assert entries[2].identity == "resource-1"
            assert observed["signature_parameters"] == 1
            assert manager.current_setup_journal() is None
            assert manager.last_failed_setup_journal is None
            assert cleanup_calls == []
        finally:
            task = observed.get("task")
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            job = observed.get("job")
            if job is not None:
                await jobs.cancel(job.id)
            await tasks.shutdown(timeout=0.05)
            await storage.close()


@pytest.mark.asyncio
async def test_setup_tracking_journals_are_isolated_between_plugin_attempts():
    """Each plugin's manager-bound tracking calls land only in its own journal during sequential setup attempts. Concurrent setup isolation is covered separately."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        observed = {}

        def make_setup(plugin_name):
            async def setup(_client):
                active_manager = PluginManager.current_manager()
                assert active_manager is manager
                active_manager.tracked_resource(
                    lambda: plugin_name,
                    lambda _resource: None,
                    kind="isolated_resource",
                    identity=plugin_name,
                )
                journal = active_manager.current_setup_journal()
                assert journal is not None
                observed[plugin_name] = {
                    "attempt_id": journal.attempt_id,
                    "entries": list(journal.entries),
                }

            return setup

        for plugin_name in (
            "plugins.phase3c_step1_isolation_a",
            "plugins.phase3c_step1_isolation_b",
        ):
            module = types.ModuleType(plugin_name)
            module.setup = make_setup(plugin_name)
            manager.records[plugin_name] = PluginRecord(plugin_name, module=module)
            await manager.enable_plugin(plugin_name)

        name_a = "plugins.phase3c_step1_isolation_a"
        name_b = "plugins.phase3c_step1_isolation_b"
        assert observed[name_a]["attempt_id"] != observed[name_b]["attempt_id"]
        assert [entry.plugin_name for entry in observed[name_a]["entries"]] == [name_a]
        assert [entry.plugin_name for entry in observed[name_b]["entries"]] == [name_b]
        assert observed[name_a]["entries"][0].attempt_id == observed[name_a]["attempt_id"]
        assert observed[name_b]["entries"][0].attempt_id == observed[name_b]["attempt_id"]
        assert manager.current_setup_journal() is None


@pytest.mark.asyncio
async def test_concurrent_setup_tracking_journals_remain_isolated():
    """Overlapping setup attempts retain task-local journals and ownership."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        a_started = asyncio.Event()
        b_finished = asyncio.Event()
        observed = {}

        name_a = "plugins.phase3c_step1_concurrent_a"
        name_b = "plugins.phase3c_step1_concurrent_b"

        async def setup_a(_client):
            active_manager = PluginManager.current_manager()
            assert active_manager is manager
            journal_a = active_manager.current_setup_journal()
            assert journal_a is not None
            assert journal_a.plugin_name == name_a
            active_manager.tracked_resource(
                lambda: "a-before-pause",
                lambda _resource: None,
                kind="isolated_resource",
                identity="a-before-pause",
            )
            a_started.set()
            await b_finished.wait()

            # B's setup has run while A is suspended. A must still see its
            # original manager, journal, and ownership after resuming.
            assert PluginManager.current_manager() is manager
            assert active_manager.current_setup_journal() is journal_a
            assert journal_a.plugin_name == name_a
            active_manager.tracked_resource(
                lambda: "a-after-resume",
                lambda _resource: None,
                kind="isolated_resource",
                identity="a-after-resume",
            )
            observed[name_a] = {
                "journal": journal_a,
                "entries": list(journal_a.entries),
            }

        async def setup_b(_client):
            await a_started.wait()
            active_manager = PluginManager.current_manager()
            assert active_manager is manager
            journal_b = active_manager.current_setup_journal()
            assert journal_b is not None
            assert journal_b.plugin_name == name_b
            active_manager.tracked_resource(
                lambda: "b-only",
                lambda _resource: None,
                kind="isolated_resource",
                identity="b-only",
            )
            assert active_manager.current_setup_journal() is journal_b
            observed[name_b] = {
                "journal": journal_b,
                "entries": list(journal_b.entries),
            }
            b_finished.set()

        module_a = types.ModuleType(name_a)
        module_a.setup = setup_a
        module_b = types.ModuleType(name_b)
        module_b.setup = setup_b
        manager.records[name_a] = PluginRecord(name_a, module=module_a)
        manager.records[name_b] = PluginRecord(name_b, module=module_b)

        await asyncio.gather(
            manager.enable_plugin(name_a),
            manager.enable_plugin(name_b),
        )

        journal_a = observed[name_a]["journal"]
        journal_b = observed[name_b]["journal"]
        entries_a = observed[name_a]["entries"]
        entries_b = observed[name_b]["entries"]
        assert journal_a is not journal_b
        assert journal_a.attempt_id != journal_b.attempt_id
        assert journal_a.plugin_name == name_a
        assert journal_b.plugin_name == name_b
        assert [entry.identity for entry in entries_a] == [
            "a-before-pause", "a-after-resume"
        ]
        assert [entry.identity for entry in entries_b] == ["b-only"]
        assert all(entry.plugin_name == name_a for entry in entries_a)
        assert all(entry.plugin_name == name_b for entry in entries_b)
        assert all(entry.attempt_id == journal_a.attempt_id for entry in entries_a)
        assert all(entry.attempt_id == journal_b.attempt_id for entry in entries_b)
        assert not any(entry.identity == "b-only" for entry in entries_a)
        assert not any(
            entry.identity in {"a-before-pause", "a-after-resume"}
            for entry in entries_b
        )
        assert manager.current_setup_journal() is None


@pytest.mark.asyncio
async def test_failed_setup_freezes_and_runs_cleanup_in_reverse_order():
    """A failed setup freezes the journal and runs tracked cleanup in reverse order."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        plugin_name = "plugins.phase3c_step1_freeze"
        cleanup_calls = []
        module = types.ModuleType(plugin_name)

        async def setup(_client):
            manager = PluginManager.current_manager()
            assert manager is not None
            manager.tracked_resource(
                lambda: "first",
                lambda value: cleanup_calls.append(value),
                kind="resource",
                identity="first",
            )
            manager.tracked_resource(
                lambda: "second",
                lambda value: cleanup_calls.append(value),
                kind="resource",
                identity="second",
            )
            raise RuntimeError("step 1 journal freeze check")

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        with pytest.raises(PluginLifecycleError, match="Enable failed"):
            await manager.enable_plugin(plugin_name)

        journal = manager.last_failed_setup_journal
        assert journal is not None
        assert journal.frozen
        assert [entry.identity for entry in journal.failure_entries] == [
            "second", "first"
        ]
        assert cleanup_calls == ["second", "first"]
        assert all(entry.cleanup_state == "SUCCEEDED" for entry in journal.entries)
        assert all(entry.cleanup_error is None for entry in journal.entries)


@pytest.mark.asyncio
async def test_step2_tracked_cleanup_is_reverse_order_and_registration_rollback_is_last():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        storage = StorageService(root / "state")
        await storage.start()
        jobs = JobEngine(storage, worker_id="phase3c-step2-order")
        tasks = TaskSupervisor()
        plugin_name = "plugins.phase3c_step2_order"
        command_pattern = r"^\.p3c2order($|\s)"
        events = []
        observed = {}
        module = types.ModuleType(plugin_name)

        async def setup(_client):
            manager = PluginManager.current_manager()
            assert manager is not None
            register_cmd(
                client, command_pattern, lambda _event: None,
                description="Step 2 rollback ordering",
            )
            def cleanup_resource(_resource):
                # Registration must still exist while tracked cleanup runs.
                assert any(
                    registration.owner == plugin_name
                    for registration in _REGISTRATIONS.values()
                )
                events.append("resource")

            manager.tracked_resource(
                lambda: object(), cleanup_resource,
                kind="test_resource", identity="resource",
            )
            observed["task"] = manager.tracked_task(
                tasks, asyncio.Event().wait(), name="phase3c-step2-task"
            )
            observed["job"] = await manager.tracked_job(
                jobs, "PHASE3C_STEP2_ORDER", {"stage": "queued"}
            )

            raise RuntimeError("original setup failure")

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        try:
            with pytest.raises(PluginLifecycleError, match="Enable failed") as raised:
                await manager.enable_plugin(plugin_name)
            assert isinstance(raised.value.__cause__, RuntimeError)
            assert str(raised.value.__cause__) == "original setup failure"
            assert events == ["resource"]
            journal = manager.last_failed_setup_journal
            assert journal is not None
            assert [entry.kind for entry in journal.failure_entries] == [
                "job", "task", "test_resource"
            ]
            assert all(
                entry.cleanup_state == "SUCCEEDED"
                for entry in journal.failure_entries
            )
            assert await jobs.get(observed["job"].id) is not None
            assert (await jobs.get(observed["job"].id)).state == JobState.CANCELLED
            assert await jobs.claim(("PHASE3C_STEP2_ORDER",)) is None
            assert not [
                item for item in tasks.active() if item.owner == plugin_name
            ]
            assert not any(
                registration.owner == plugin_name
                for registration in _REGISTRATIONS.values()
            )
            assert manager.get(plugin_name).error == "original setup failure"
        finally:
            task = observed.get("task")
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            job = observed.get("job")
            if job is not None:
                await jobs.cancel(job.id)
            await tasks.shutdown(timeout=0.05)
            await storage.close()
            for registration in list(_REGISTRATIONS.values()):
                if registration.owner == plugin_name:
                    registration.unregister(client)


@pytest.mark.asyncio
async def test_step2_cleanup_failure_does_not_stop_unwind_or_mask_setup_error():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        plugin_name = "plugins.phase3c_step2_partial_failure"
        events = []
        module = types.ModuleType(plugin_name)

        async def setup(_client):
            manager = PluginManager.current_manager()
            assert manager is not None
            manager.tracked_resource(
                lambda: "first",
                lambda _value: events.append("first"),
                kind="test_resource", identity="first",
            )

            def broken_cleanup(_value):
                events.append("broken")
                raise ValueError("cleanup exploded")

            manager.tracked_resource(
                lambda: "broken",
                broken_cleanup,
                kind="test_resource", identity="broken",
            )
            manager.tracked_resource(
                lambda: "last",
                lambda _value: events.append("last"),
                kind="test_resource", identity="last",
            )
            raise RuntimeError("primary setup failure")

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        with pytest.raises(PluginLifecycleError, match="Enable failed") as raised:
            await manager.enable_plugin(plugin_name)

        assert isinstance(raised.value.__cause__, RuntimeError)
        assert str(raised.value.__cause__) == "primary setup failure"
        assert events == ["last", "broken", "first"]
        journal = manager.last_failed_setup_journal
        assert journal is not None
        by_identity = {entry.identity: entry for entry in journal.entries}
        assert by_identity["last"].cleanup_state == "SUCCEEDED"
        assert by_identity["first"].cleanup_state == "SUCCEEDED"
        assert by_identity["broken"].cleanup_state == "FAILED"
        assert "ValueError: cleanup exploded" in by_identity["broken"].cleanup_error
        assert len(journal.cleanup_errors) == 1
        assert "broken" in journal.cleanup_errors[0]
        assert manager.get(plugin_name).error == "primary setup failure"


@pytest.mark.asyncio
async def test_step2_failed_plugin_cleanup_does_not_touch_overlapping_plugin_journal():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        b_started = asyncio.Event()
        release_b = asyncio.Event()
        cleaned = []
        observed = {}
        name_a = "plugins.phase3c_step2_overlap_a"
        name_b = "plugins.phase3c_step2_overlap_b"

        async def setup_a(_client):
            active = PluginManager.current_manager()
            assert active is manager
            active.tracked_resource(
                lambda: "A",
                lambda value: cleaned.append(value),
                kind="resource", identity="A",
            )
            await b_started.wait()
            raise RuntimeError("A setup failure")

        async def setup_b(_client):
            active = PluginManager.current_manager()
            assert active is manager
            resource = active.tracked_resource(
                lambda: "B",
                lambda value: cleaned.append(value),
                kind="resource", identity="B",
            )
            observed["journal_b"] = active.current_setup_journal()
            observed["resource_b"] = resource
            b_started.set()
            await release_b.wait()
            assert active.current_setup_journal() is observed["journal_b"]
            assert observed["journal_b"] is not None
            assert observed["journal_b"].plugin_name == name_b

        module_a = types.ModuleType(name_a)
        module_a.setup = setup_a
        module_b = types.ModuleType(name_b)
        module_b.setup = setup_b
        manager.records[name_a] = PluginRecord(name_a, module=module_a)
        manager.records[name_b] = PluginRecord(name_b, module=module_b)

        task_b = asyncio.create_task(manager.enable_plugin(name_b))
        try:
            with pytest.raises(PluginLifecycleError, match="Enable failed"):
                await manager.enable_plugin(name_a)
            assert cleaned == ["A"]
            journal_a = manager.last_failed_setup_journal
            assert journal_a is not None
            assert [entry.identity for entry in journal_a.entries] == ["A"]
            assert observed["journal_b"] is not journal_a
            assert observed["journal_b"].plugin_name == name_b
            assert [entry.identity for entry in observed["journal_b"].entries] == ["B"]
            assert observed["journal_b"].entries[0].cleanup_state == "PENDING"
        finally:
            release_b.set()
            await task_b
        assert cleaned == ["A"]
        assert manager.get(name_b).state.name == "RUNNING"

@pytest.mark.asyncio
async def test_step2_async_cleanup_timeout_is_recorded_and_later_cleanup_runs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        plugin_name = "plugins.phase3c_step2_cleanup_timeout"
        events = []
        never = asyncio.Event()
        module = types.ModuleType(plugin_name)

        async def setup(_client):
            manager = PluginManager.current_manager()
            assert manager is not None
            manager._SETUP_CLEANUP_TIMEOUT_SECONDS = 0.01

            async def hanging_cleanup(_value):
                await never.wait()

            manager.tracked_resource(
                lambda: "hanging", hanging_cleanup,
                kind="test_resource", identity="hanging",
            )
            manager.tracked_resource(
                lambda: "later",
                lambda _value: events.append("later"),
                kind="test_resource", identity="later",
            )
            raise RuntimeError("setup failed before cleanup timeout")

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        with pytest.raises(PluginLifecycleError, match="Enable failed") as raised:
            await manager.enable_plugin(plugin_name)

        assert str(raised.value.__cause__) == "setup failed before cleanup timeout"
        journal = manager.last_failed_setup_journal
        assert journal is not None
        entries = {entry.identity: entry for entry in journal.entries}
        assert entries["hanging"].cleanup_state == "FAILED"
        assert "TimeoutError" in entries["hanging"].cleanup_error
        assert entries["later"].cleanup_state == "SUCCEEDED"
        assert events == ["later"]
        assert len(journal.cleanup_errors) == 1
        assert manager.get(plugin_name).error == "setup failed before cleanup timeout"


@pytest.mark.asyncio
async def test_step3_claimed_tracked_job_is_uncertain_not_cleanly_rolled_back():
    """A job claimed before setup fails is uncertain, not a successful rollback."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        storage = StorageService(root / "state")
        await storage.start()
        jobs = JobEngine(storage, worker_id="phase3c-step3-claim-worker")
        tasks = TaskSupervisor()
        plugin_name = "plugins.phase3c_step3_claim_race"
        command_pattern = r"^\.p3c3claim($|\s)"
        observed = {}
        module = types.ModuleType(plugin_name)

        async def setup(_client):
            manager = PluginManager.current_manager()
            assert manager is not None
            register_cmd(
                client,
                command_pattern,
                lambda _event: None,
                description="Step 3 claimed-job uncertainty",
            )
            observed["task"] = manager.tracked_task(
                tasks,
                asyncio.Event().wait(),
                name="phase3c-step3-claim-task",
            )
            queued = await manager.tracked_job(
                jobs,
                "PHASE3C_STEP3_CLAIM_RACE",
                {"stage": "claimed-before-rollback"},
            )
            observed["queued"] = queued

            # Deterministically simulate the worker winning the claim race
            # before plugin setup fails; no JobEngine.enqueue changes required.
            claimed = await jobs.claim(("PHASE3C_STEP3_CLAIM_RACE",))
            assert claimed is not None
            assert claimed.id == queued.id
            assert claimed.state == JobState.RUNNING
            observed["claimed"] = claimed
            raise RuntimeError("setup failed after worker claimed job")

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        try:
            with pytest.raises(PluginLifecycleError, match="Enable failed") as raised:
                await manager.enable_plugin(plugin_name)
            assert str(raised.value.__cause__) == "setup failed after worker claimed job"

            current = await jobs.get(observed["queued"].id)
            assert current.state == JobState.UNCERTAIN

            journal = manager.last_failed_setup_journal
            assert journal is not None
            by_identity = {entry.identity: entry for entry in journal.entries}
            job_entry = by_identity[observed["queued"].id]
            assert job_entry.kind == "job"
            assert job_entry.cleanup_state == "UNCERTAIN"
            assert job_entry.cleanup_error is not None
            assert "claimed before setup rollback" in job_entry.cleanup_error
            # UNCERTAIN is a distinct cleanup outcome, not a cleanup failure.
            # Its state and explanation are recorded on the journal entry above;
            # journal.cleanup_errors is reserved for actual cleanup failures.
            assert by_identity[
                next(entry.identity for entry in journal.entries if entry.kind == "task")
            ].cleanup_state == "SUCCEEDED"
            assert [entry.kind for entry in journal.failure_entries] == ["job", "task"]
            assert observed["task"].done() and observed["task"].cancelled()
            assert not [
                item for item in tasks.active()
                if item.owner == plugin_name
            ]
            assert not any(
                registration.owner == plugin_name
                for registration in _REGISTRATIONS.values()
            )
            assert manager.get(plugin_name).error == "setup failed after worker claimed job"
        finally:
            task = observed.get("task")
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await tasks.shutdown(timeout=0.05)
            await storage.close()
            for registration in list(_REGISTRATIONS.values()):
                if registration.owner == plugin_name:
                    registration.unregister(client)

@pytest.mark.asyncio
async def test_step2_setup_started_failure_has_empty_journal_and_no_cleanup():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        client = FakeClient()
        plugin_name = "plugins.phase3c_step2_empty_journal"
        module = types.ModuleType(plugin_name)

        async def setup(_client):
            raise RuntimeError("failure before tracked side effects")

        module.setup = setup
        manager = PluginManager(client, root / "plugins")
        client.plugin_manager = manager
        manager.records[plugin_name] = PluginRecord(plugin_name, module=module)

        with pytest.raises(PluginLifecycleError, match="Enable failed") as raised:
            await manager.enable_plugin(plugin_name)

        assert str(raised.value.__cause__) == "failure before tracked side effects"
        journal = manager.last_failed_setup_journal
        assert journal is not None
        assert journal.frozen
        assert journal.entries == []
        assert journal.failure_entries == ()
        assert journal.cleanup_errors == []
        assert manager.get(plugin_name).error == "failure before tracked side effects"

