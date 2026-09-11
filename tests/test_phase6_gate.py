import asyncio
import base64
import re
import unittest

from plugins.security import acl, pmguard
from plugins.admin_ops import advanced_admin
from plugins.system import eval as eval_plugin
from core.services.secrets import SecretStore


class FakeSecretDB:
    def __init__(self):
        self.values = {}
        self.schema_initialized = False

    async def init_schema(self, _ddl):
        self.schema_initialized = True

    async def execute(self, sql, parameters=()):
        if sql.startswith("INSERT OR REPLACE INTO secrets"):
            self.values[parameters[0]] = parameters[1]
        elif sql.startswith("DELETE FROM secrets"):
            self.values.pop(parameters[0], None)

    async def fetchone(self, _sql, parameters=()):
        value = self.values.get(parameters[0])
        return (value,) if value is not None else None

    async def fetchall(self, _sql):
        return [(key,) for key in sorted(self.values)]


class FakePattern:
    def __init__(self, value):
        self.value = value

    def group(self, number):
        return self.value if number == 1 else None


class FakeEvent:
    def __init__(self, code):
        self.pattern_match = FakePattern(code)
        self.client = object()
        self.responses = []

    async def edit(self, text):
        self.responses.append(text)


class Phase6GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_secret_store_encrypts_and_round_trips(self):
        db = FakeSecretDB()
        store = SecretStore(db=db, master_key="phase6-test-key")
        await store.set("token", "super-secret")
        self.assertTrue(db.schema_initialized)
        self.assertNotEqual(db.values["token"], "super-secret")
        self.assertTrue(db.values["token"].startswith("v1:"))
        self.assertEqual(await store.get("token"), "super-secret")

    async def test_secret_store_migrates_legacy_base64_entry(self):
        db = FakeSecretDB()
        db.values["legacy"] = base64.b64encode(b"old-secret").decode()
        store = SecretStore(db=db, master_key="phase6-test-key")
        self.assertEqual(await store.get("legacy"), "old-secret")
        self.assertTrue(db.values["legacy"].startswith("v1:"))

    async def test_block_commands_have_one_owner(self):
        self.assertRegex(acl.PATTERN, r"block\|unblock")
        self.assertNotRegex(pmguard.PATTERN, r"block\|unblock")

    async def test_advertised_admin_commands_are_registered(self):
        for command in ("purge", "purgeme", "zombies", "promote", "demote", "slow", "kickme"):
            self.assertIn(command, advanced_admin.PATTERN)

    async def test_eval_serializes_global_stdout_capture(self):
        first = FakeEvent('print("first"); await asyncio.sleep(0.02); print("first-end")')
        second = FakeEvent('print("second"); await asyncio.sleep(0.02); print("second-end")')
        await asyncio.gather(eval_plugin.handle_eval(first), eval_plugin.handle_eval(second))
        self.assertEqual(len(first.responses), 1)
        self.assertEqual(len(second.responses), 1)
        self.assertIn("first", first.responses[0])
        self.assertIn("first-end", first.responses[0])
        self.assertNotIn("second", first.responses[0])
        self.assertIn("second", second.responses[0])
        self.assertIn("second-end", second.responses[0])
        self.assertNotIn("first-end", second.responses[0])


if __name__ == "__main__":
    unittest.main()
