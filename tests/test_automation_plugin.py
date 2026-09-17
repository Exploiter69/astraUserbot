import asyncio
import re
import unittest

from core.registry import COMMANDS, clear_registrations
from plugins import automation


class FakeClient:
    def __init__(self):
        self.handlers = []

    def add_event_handler(self, callback, builder):
        self.handlers.append((callback, builder))

    def remove_event_handler(self, callback, builder):
        self.handlers.remove((callback, builder))


class AutomationPluginRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        clear_registrations(self.client)

    def tearDown(self):
        clear_registrations(self.client)

    def test_setup_registers_autorule_family_without_collision(self):
        asyncio.run(automation.setup(self.client))

        self.assertEqual(len(self.client.handlers), 2)
        patterns = set(COMMANDS)
        self.assertIn(r"^\.autorule\s+(list|show|create|enable|disable|delete|run)(?:\s+(\S+))?(?:\s+(.+))?$", patterns)
        self.assertIn(r"^\.autostatus$", patterns)

    def test_autorule_pattern_preserves_all_subcommands(self):
        asyncio.run(automation.setup(self.client))
        autorule_pattern = next(pattern for pattern in COMMANDS if "autorule" in pattern)

        matcher = re.compile(autorule_pattern)
        cases = {
            ".autorule list": ("list", None, None),
            ".autorule show rule1": ("show", "rule1", None),
            ".autorule create rule1 {\"actions\": []}": ("create", "rule1", '{"actions": []}'),
            ".autorule enable rule1": ("enable", "rule1", None),
            ".autorule disable rule1": ("disable", "rule1", None),
            ".autorule delete rule1": ("delete", "rule1", None),
            ".autorule run rule1": ("run", "rule1", None),
        }
        for command, expected in cases.items():
            match = matcher.fullmatch(command)
            self.assertIsNotNone(match, command)
            self.assertEqual(match.groups(), expected, command)


if __name__ == "__main__":
    unittest.main()
