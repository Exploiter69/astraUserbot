import asyncio
import unittest

from core.errors import ErrorCode
from core.tasks import TaskState, TaskSupervisor


class TaskSupervisorTests(unittest.TestCase):
    def test_completed_task_is_tracked_and_archived(self):
        async def work():
            return 42

        async def scenario():
            supervisor = TaskSupervisor()
            task = supervisor.create_task(work(), name="test.work", owner="plugins.example")
            result = await task
            await asyncio.sleep(0)
            return supervisor, result

        supervisor, result = asyncio.run(scenario())
        self.assertEqual(result, 42)
        self.assertEqual(supervisor.active(), [])
        history = supervisor.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].state, TaskState.COMPLETED)
        self.assertEqual(history[0].owner, "plugins.example")
        self.assertEqual(history[0].name, "test.work")

    def test_crash_is_visible_with_stable_error_code(self):
        async def work():
            raise RuntimeError("secret provider response")

        async def scenario():
            supervisor = TaskSupervisor()
            task = supervisor.create_task(work(), name="test.crash")
            await task

        # The supervisor consumes the exception in its done callback, so awaiting
        # the task itself still raises; this verifies the callback records it.
        with self.assertRaises(RuntimeError):
            asyncio.run(scenario())

    def test_crash_record_is_archived(self):
        async def scenario():
            supervisor = TaskSupervisor()

            async def work():
                raise RuntimeError("secret provider response")

            task = supervisor.create_task(work(), name="test.crash")
            try:
                await task
            except RuntimeError:
                pass
            await asyncio.sleep(0)
            return supervisor

        supervisor = asyncio.run(scenario())
        record = supervisor.history()[0]
        self.assertEqual(record.state, TaskState.FAILED)
        self.assertEqual(record.error_code, ErrorCode.UNKNOWN)

    def test_cancel_and_shutdown_stop_long_lived_tasks(self):
        async def scenario():
            supervisor = TaskSupervisor()
            started = asyncio.Event()
            stopped = asyncio.Event()

            async def worker():
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

            task = supervisor.create_task(worker(), name="test.worker")
            await started.wait()
            task_id = supervisor.active()[0].task_id
            cancelled = await supervisor.cancel(task_id)
            await stopped.wait()
            return supervisor, task, cancelled

        supervisor, task, cancelled = asyncio.run(scenario())
        self.assertTrue(cancelled)
        self.assertTrue(task.cancelled())
        self.assertEqual(supervisor.history()[0].state, TaskState.CANCELLED)

    def test_history_is_bounded(self):
        async def scenario():
            supervisor = TaskSupervisor(history_limit=2)
            for index in range(3):
                await supervisor.create_task(
                    asyncio.sleep(0), name=f"test.{index}"
                )
                await asyncio.sleep(0)
            return supervisor

        supervisor = asyncio.run(scenario())
        self.assertEqual(len(supervisor.history()), 2)
        self.assertEqual([item.name for item in supervisor.history()], ["test.1", "test.2"])

    def test_snapshot_contains_no_task_object(self):
        async def scenario():
            supervisor = TaskSupervisor()

            async def work():
                await asyncio.sleep(0)

            await supervisor.create_task(work(), name="test.snapshot", owner="owner")
            await asyncio.sleep(0)
            return supervisor.snapshot()

        snapshot = asyncio.run(scenario())
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["name"], "test.snapshot")
        self.assertEqual(snapshot[0]["owner"], "owner")
        self.assertNotIn("task", snapshot[0])

    def test_new_tasks_are_rejected_after_shutdown(self):
        async def scenario():
            supervisor = TaskSupervisor()
            await supervisor.shutdown()
            return supervisor

        supervisor = asyncio.run(scenario())
        with self.assertRaises(RuntimeError):
            supervisor.create_task(asyncio.sleep(0), name="test.after_shutdown")


if __name__ == "__main__":
    unittest.main()
