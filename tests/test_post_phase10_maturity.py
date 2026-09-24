from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.registry import CommandRegistration, command_metadata, recent_registrations, register_cmd
from core.services.search import SearchResult
from helpers.ux import bounded_callback_token, form_buttons, gallery_buttons, list_buttons, parse_callback_token


class PostPhase10ContractTests(unittest.TestCase):
    def test_command_contract_contains_maturity_fields(self):
        registration = CommandRegistration(
            registration_id="test-id",
            pattern=r"^\.example(?:\s+(.*))?$",
            handler=lambda event: None,
            category="test",
            description="example",
            aliases=("ex",),
            permission="owner",
            operation_class="READ",
            required_capabilities=("search.read",),
            examples=(".example",),
            compatibility="1.0",
            network=False,
            durable_job=False,
            destructive=False,
            confirmation_required=False,
            resource_class="default",
            source_ref="tests",
            usage=".example <text>",
        )
        metadata = command_metadata(registration)
        self.assertEqual(metadata["names"], ["example", "ex"])
        self.assertEqual(metadata["operation_class"], "READ")
        self.assertEqual(metadata["required_capabilities"], ["search.read"])
        self.assertEqual(metadata["compatibility"], "1.0")
        self.assertEqual(metadata["usage"], ".example <text>")

    def test_register_cmd_infers_safe_read_contract(self):
        client = Mock()
        registration = register_cmd(
            client,
            r"^\.maturityread$",
            lambda event: None,
            category="system",
            description="Read-only maturity probe.",
        )
        try:
            self.assertEqual(registration.operation_class, "READ")
            self.assertFalse(registration.network)
            self.assertFalse(registration.destructive)
            self.assertEqual(registration.compatibility, "1.0")
            self.assertTrue(registration.examples)
        finally:
            registration.unregister(client)

    def test_recent_command_discovery_never_contains_arguments(self):
        client = Mock()
        registration = register_cmd(client, r"^\\.recentprobe(?:\\s+(.*))?$", lambda event: None, category="system", description="Recent probe")
        try:
            recent = recent_registrations(5)
            self.assertTrue(any(item.registration_id == registration.registration_id for item in recent))
            self.assertFalse(any("secret" in str(item) for item in recent))
        finally:
            registration.unregister(client)

    def test_search_result_has_stable_identifier_contract(self):
        result = SearchResult("command", "abc", ".help", "help", -1.0, result_id="command:abc", evidence_ref="abc")
        self.assertEqual(result.result_id, "command:abc")
        self.assertEqual(result.evidence_ref, "abc")

    def test_ux_callback_contracts_are_bounded(self):
        token = bounded_callback_token("inspect", "x" * 100)
        self.assertLessEqual(len(token), 96)
        self.assertTrue(form_buttons("case-1"))
        self.assertTrue(gallery_buttons("media-1", 0, has_next=True))
        self.assertTrue(list_buttons("search", 0, has_next=True))
        self.assertEqual(parse_callback_token(b"ux:search:page:2"), ("ux", "search", "page", "2"))
        with self.assertRaises(ValueError):
            parse_callback_token(b"x" * 97)

    def test_product_spine_surfaces_exist(self):
        root = Path(__file__).resolve().parents[1]
        product = (root / "plugins/system_ops/product_surface.py").read_text(encoding="utf-8")
        help_text = (root / "plugins/system/help.py").read_text(encoding="utf-8")
        self.assertIn("inspect|correlate", product)
        self.assertIn("plugin", product)
        self.assertIn("aiux", product)
        self.assertIn("doctor|config|update|restart", product)
        self.assertIn("command search", help_text) or self.assertIn("COMMAND_PATTERN", help_text)

    def test_help_surface_documents_canonical_command_or_category_discovery(self):
        root = Path(__file__).resolve().parents[1]
        help_text = (root / "plugins/system/help.py").read_text(encoding="utf-8")
        self.assertIn(".help <command-or-category>", help_text)


if __name__ == "__main__":
    unittest.main()
