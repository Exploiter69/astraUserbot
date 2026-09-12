import asyncio
import unittest

from core.plugins.manager import PluginManager, PluginRecord, PluginState
from core.registry import (
    COMMANDS,
    CommandRegistrationError,
    clear_registrations,
    register_cmd,
)


class FakeClient:
    def __init__(self):
        self.handlers = []

    def add_event_handler(self, callback, builder):
        self.handlers.append((callback, builder))

    def remove_event_handler(self, callback, builder):
        self.handlers.remove((callback, builder))


class CommandRouterTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        clear_registrations(self.client)

    def tearDown(self):
        clear_registrations(self.client)

    def test_duplicate_command_token_is_rejected(self):
        async def first(event):
            pass

        async def second(event):
            pass

        register_cmd(self.client, r"^\\.block$", first)
        with self.assertRaises(CommandRegistrationError):
            register_cmd(self.client, r"^\\.block(?:\\s+(.*))?$", second)
        self.assertEqual(len(self.client.handlers), 1)

    def test_grouped_commands_reserve_each_token(self):
        async def handler(event):
            pass

        async def conflicting(event):
            pass

        register_cmd(self.client, r"^\\.(block|unblock)$", handler)
        with self.assertRaises(CommandRegistrationError):
            register_cmd(self.client, r"^\\.unblock$", conflicting)

    def test_registration_records_owner_and_metadata(self):
        manager = PluginManager(self.client, __import__("pathlib").Path("/tmp/plugins"))
        manager.records["plugins.example"] = PluginRecord(
            "plugins.example", state=PluginState.RUNNING
        )
        self.client.plugin_manager = manager
        token = PluginManager._current_plugin.set("plugins.example")
        try:
            async def handler(event):
                pass

            registration = register_cmd(
                self.client,
                r"^\\.ping$",
                handler,
                category="system",
                description="Ping",
                aliases=["p"],
                permission="owner",
            )
        finally:
            PluginManager._current_plugin.reset(token)

        self.assertEqual(registration.owner, "plugins.example")
        self.assertEqual(registration.aliases, ("p",))
        self.assertEqual(COMMANDS[registration.pattern]["owner"], "plugins.example")
        self.assertIn(registration.registration_id, manager.records["plugins.example"].registrations)

    def test_registered_command_is_outgoing_only(self):
        async def handler(event):
            pass

        registration = register_cmd(self.client, r"^\\.ping$", handler)
        builder = registration.event_builder
        self.assertIsNotNone(builder)
        self.assertTrue(builder.outgoing)
        self.assertFalse(builder.incoming)

    def test_unregister_removes_handler_and_registry_state(self):
        async def handler(event):
            pass

        registration = register_cmd(self.client, r"^\\.ping$", handler)
        self.assertEqual(len(self.client.handlers), 1)
        registration.unregister(self.client)
        self.assertEqual(self.client.handlers, [])
        self.assertNotIn(registration.pattern, COMMANDS)

    def test_unexpected_handler_error_is_not_exposed(self):
        async def handler(event):
            raise RuntimeError("/secret/path/provider-response")

        registration = register_cmd(self.client, r"^\\.boom$", handler)

        class Event:
            out = True
            edited = None

            async def edit(self, value):
                self.edited = value

        event = Event()
        asyncio.run(registration.wrapper(event))
        self.assertNotIn("/secret/path", event.edited)
        self.assertNotIn("provider-response", event.edited)
        self.assertIn("Reference:", event.edited)


if __name__ == "__main__":
    unittest.main()
