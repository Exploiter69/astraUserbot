import asyncio
import importlib
import unittest


class FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    async def fetchall(self, _sql, _parameters=()):
        return list(self.rows)

    async def execute(self, _sql, parameters=()):
        self.updates.append(parameters)


class FakeSender:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    async def send_message(self, entity, message, **kwargs):
        if self.fail:
            raise RuntimeError("temporary telegram failure")
        self.calls.append((entity, message, kwargs))
        return object()


class ProductivityReminderTests(unittest.TestCase):
    def test_due_reminder_is_sent_and_marked_delivered(self):
        module = importlib.import_module("plugins.productivity")
        db = FakeDB([(7, 123, 456, "hello")])
        sender = FakeSender()
        original = module.DB
        module.DB = db
        try:
            delivered = asyncio.run(module._deliver_due_reminders(sender, now=1000.0))
        finally:
            module.DB = original
        self.assertEqual(delivered, 1)
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(db.updates, [(7,)])

    def test_failed_delivery_remains_pending_for_retry(self):
        module = importlib.import_module("plugins.productivity")
        db = FakeDB([(8, 123, 456, "retry me")])
        sender = FakeSender(fail=True)
        original = module.DB
        module.DB = db
        try:
            delivered = asyncio.run(module._deliver_due_reminders(sender, now=1000.0))
        finally:
            module.DB = original
        self.assertEqual(delivered, 0)
        self.assertEqual(len(sender.calls), 0)
        self.assertEqual(db.updates, [])

    def test_setup_source_uses_task_supervisor_when_context_exists(self):
        module = importlib.import_module("plugins.productivity")
        source = open(module.__file__, encoding="utf-8").read()
        self.assertIn('context.tasks.create_task(_reminder_worker(context.get("telegram"))', source)
        self.assertIn('name="productivity.reminder_worker"', source)


if __name__ == "__main__":
    unittest.main()
