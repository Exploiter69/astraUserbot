import unittest

from core.errors import CommandError
from core.registry import clear_registrations, list_registrations
from plugins.system_ops import telegram_traffic


class FakeStorage:
    def __init__(self):
        self.calls = []

    async def fetchall(self, sql, params=()):
        self.calls.append((sql, params))
        if "GROUP BY peer_id" in sql:
            return [("chat:1", 3, 2, 1, 12.5)]
        if "GROUP BY method" in sql:
            return [("send_message", 4, 3, 1, 10.0)]
        if "WHERE peer_id = ?" in sql:
            return [("1", "send_message", "chat:1", "WRITE", "SUCCESS", 10.0, None, None, 0)]
        return []


class FakeTelegram:
    def __init__(self):
        self._snapshot = {
            "queued": 1,
            "active": 2,
            "max_concurrency": 8,
            "effective_concurrency": 4,
            "per_method_limit": 4,
            "per_peer_limit": 2,
            "max_queue": 512,
            "starved": 0,
            "cooldowns": {"method:send_message": 1.0},
            "governor": {"account": {"state": "THROTTLED", "pressure": 2, "cooldown_seconds": 1.0}},
            "counters": {"queued": 5, "completed": 3, "flood_wait": 1},
        }

    def traffic_snapshot(self):
        return self._snapshot


class FakeContext:
    def __init__(self):
        self.services = {"telegram": FakeTelegram(), "storage": FakeStorage()}

    def get(self, name):
        return self.services[name]


class FakeMatch:
    def __init__(self, command, arg=""):
        self.command = command
        self.arg = arg

    def group(self, index):
        return self.command if index == 1 else self.arg


class FakeEvent:
    def __init__(self, command, arg=""):
        self.pattern_match = FakeMatch(command, arg)
        self.output = None

    async def edit(self, value):
        self.output = value


class TelegramTrafficOperatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        client = type("Client", (), {})()
        clear_registrations(client)
        self.old_ctx = telegram_traffic.get_application_context
        telegram_traffic.get_application_context = lambda: FakeContext()

    def tearDown(self):
        telegram_traffic.get_application_context = self.old_ctx

    async def test_setup_registers_all_phase_commands(self):
        client = type("Client", (), {})()
        await telegram_traffic.setup(client)
        registrations = list_registrations()
        self.assertEqual(len(registrations), 1)
        pattern = registrations[0].pattern
        for name in ("tghealth", "tgtraffic", "tgfloods", "tgpeer", "tgmethod", "tgdiag"):
            self.assertIn(name, pattern)
        clear_registrations(client)

    async def test_health_and_traffic_are_bounded_snapshots(self):
        event = FakeEvent("tghealth")
        await telegram_traffic.handle(event)
        self.assertIn("THROTTLED", event.output)
        self.assertIn("Queued: 1 / 512", event.output)

        event = FakeEvent("tgtraffic")
        await telegram_traffic.handle(event)
        self.assertIn("Concurrency: 4 / 8", event.output)
        self.assertIn("flood_wait=1", event.output)

    async def test_peer_and_method_queries_are_parameterized(self):
        event = FakeEvent("tgpeer", "chat:1")
        await telegram_traffic.handle(event)
        self.assertIn("Peer: chat:1", event.output)

        event = FakeEvent("tgmethod", "send_message")
        await telegram_traffic.handle(event)
        self.assertIn("Method: send_message", event.output)

    async def test_missing_peer_is_rejected(self):
        with self.assertRaises(CommandError):
            await telegram_traffic.handle(FakeEvent("tgpeer"))


if __name__ == "__main__":
    unittest.main()
