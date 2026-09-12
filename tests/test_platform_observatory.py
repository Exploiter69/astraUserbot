import unittest
from unittest.mock import patch

from core.errors import CommandError
from plugins.system_ops.platform import (
    _command_names,
    _display_command,
    _find_plugin,
    _pack,
    _plugin_command_map,
    _plugin_detail,
    _plugin_overview,
)


class FakeRegistration:
    def __init__(self, owner, pattern, aliases=()):
        self.owner = owner
        self.pattern = pattern
        self.aliases = tuple(aliases)


class PluginObservatoryTests(unittest.TestCase):
    def test_pack_is_bounded_and_reports_overflow(self):
        rows = _pack([f"plugin-{index}" for index in range(85)])
        self.assertEqual(len(rows), 28)
        self.assertEqual(rows[-1], "… +5 more")

    def test_find_plugin_supports_short_name_and_rejects_ambiguity(self):
        records = [
            {"name": "plugins.system_ops.platform", "state": "RUNNING"},
            {"name": "plugins.system_ops.help", "state": "RUNNING"},
        ]
        self.assertEqual(_find_plugin(records, "system_ops.platform")["name"], "plugins.system_ops.platform")
        with self.assertRaisesRegex(CommandError, "ambiguous"):
            _find_plugin(records, "system_ops")

    def test_overview_reports_states_commands_and_attention(self):
        records = [
            {"name": "plugins.alpha", "state": "RUNNING"},
            {"name": "plugins.beta", "state": "FAILED_SETUP"},
            {"name": "plugins.gamma", "state": "DISABLED"},
        ]
        rows = _plugin_overview(records, {"plugins.alpha": 3, "plugins.beta": 1})
        text = "\n".join(rows)
        self.assertIn("Plugins: 3  ·  Commands: 4", text)
        self.assertIn("RUNNING: 1", text)
        self.assertIn("FAILED_SETUP: 1", text)
        self.assertIn("ATTENTION", text)
        self.assertIn("beta → FAILED_SETUP", text)
        self.assertIn("gamma → DISABLED", text)

    def test_command_map_uses_live_registration_ownership(self):
        registrations = [
            FakeRegistration("plugins.alpha", ".a"),
            FakeRegistration("plugins.alpha", ".alpha"),
            FakeRegistration("plugins.beta", ".b"),
            FakeRegistration(None, ".legacy"),
        ]
        with patch("plugins.system_ops.platform.list_registrations", return_value=registrations):
            self.assertEqual(_plugin_command_map(), {"plugins.alpha": 2, "plugins.beta": 1})

    def test_detail_uses_friendly_command_names(self):
        record = {
            "name": "plugins.alpha", "state": "RUNNING", "critical": True,
            "dependencies": ["plugins.base"], "error": None,
        }
        with patch(
            "plugins.system_ops.platform.list_registrations",
            return_value=[
                FakeRegistration("plugins.alpha", r"^\.alpha(?:\s+(.*))?$"),
                FakeRegistration("plugins.alpha", r"^\.a$", aliases=(".alias",)),
            ],
        ):
            rows = _plugin_detail(record, {"plugins.alpha": 2})
        text = "\n".join(rows)
        self.assertIn("Plugin: alpha", text)
        self.assertIn("State: RUNNING", text)
        self.assertIn("Commands: 2", text)
        self.assertIn("Critical: YES", text)
        self.assertIn("Dependencies: base", text)
        self.assertIn("COMMANDS", text)
        self.assertIn(".alpha", text)
        self.assertIn(".a  .alias", text)
        self.assertNotIn("(?:\\s+", text)

    def test_command_names_support_grouped_commands_and_aliases(self):
        registration = FakeRegistration(
            "plugins.alpha", r"^\.(health|status|ops)(?:\s+(.*))?$", aliases=(".h",)
        )
        self.assertEqual(_command_names(registration), ("health", "status", "ops", "h"))
        self.assertEqual(_display_command(registration), ".health  .status  .ops  .h")


if __name__ == "__main__":
    unittest.main()
