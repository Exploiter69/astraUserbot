from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from core.registry import (
    CommandRegistration,
    command_metadata,
    recent_registrations,
    register_cmd,
)
from core.services.search import SearchResult
from helpers.ux import (
    bounded_callback_token,
    form_buttons,
    gallery_buttons,
    list_buttons,
    parse_callback_token,
)


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
            argument_schema={"text": {"type": "string", "required": True}},
            priority=200,
            timeout_seconds=15.0,
            cancellation_supported=True,
            durable_execution_supported=False,
            source_ref="tests",
            owner_version="1.2.3",
            usage=".example <text>",
        )
        metadata = command_metadata(registration)
        self.assertEqual(metadata["names"], ["example", "ex"])
        self.assertEqual(metadata["operation_class"], "READ")
        self.assertEqual(metadata["required_capabilities"], ["search.read"])
        self.assertEqual(metadata["compatibility"], "1.0")
        self.assertEqual(metadata["usage"], ".example <text>")
        self.assertEqual(metadata["argument_schema"]["text"]["type"], "string")
        self.assertEqual(metadata["priority"], 200)
        self.assertEqual(metadata["timeout_seconds"], 15.0)
        self.assertTrue(metadata["cancellation_supported"])
        self.assertFalse(metadata["durable_execution_supported"])
        self.assertEqual(metadata["owner_version"], "1.2.3")

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
            self.assertEqual(registration.priority, 100)
            self.assertEqual(registration.timeout_seconds, 30.0)
            self.assertFalse(registration.cancellation_supported)
            self.assertFalse(registration.durable_execution_supported)
        finally:
            registration.unregister(client)

    def test_recent_command_discovery_never_contains_arguments(self):
        client = Mock()
        registration = register_cmd(
            client,
            r"^\\.recentprobe(?:\\s+(.*))?$",
            lambda event: None,
            category="system",
            description="Recent probe",
        )
        try:
            recent = recent_registrations(5)
            self.assertTrue(
                any(
                    item.registration_id == registration.registration_id
                    for item in recent
                )
            )
            self.assertFalse(any("secret" in str(item) for item in recent))
        finally:
            registration.unregister(client)

    def test_search_result_has_stable_identifier_contract(self):
        result = SearchResult(
            "command",
            "abc",
            ".help",
            "help",
            -1.0,
            result_id="command:abc",
            evidence_ref="abc",
        )
        self.assertEqual(result.result_id, "command:abc")
        self.assertEqual(result.evidence_ref, "abc")

    def test_ux_callback_contracts_are_bounded(self):
        token = bounded_callback_token("inspect", "x" * 100)
        self.assertLessEqual(len(token), 96)
        self.assertTrue(form_buttons("case-1"))
        self.assertTrue(gallery_buttons("media-1", 0, has_next=True))
        self.assertTrue(list_buttons("search", 0, has_next=True))
        self.assertEqual(
            parse_callback_token(b"ux:search:page:2"), ("ux", "search", "page", "2")
        )
        with self.assertRaises(ValueError):
            parse_callback_token(b"x" * 97)

    def test_product_spine_surfaces_exist(self):
        root = Path(__file__).resolve().parents[1]
        product = (root / "plugins/system_ops/product_surface.py").read_text(
            encoding="utf-8"
        )
        help_text = (root / "plugins/system/help.py").read_text(encoding="utf-8")
        self.assertIn("inspect|correlate", product)
        self.assertIn("plugin", product)
        self.assertIn("aiux", product)
        self.assertIn("config|restart", product)
        self.assertIn("command search", help_text) or self.assertIn(
            "COMMAND_PATTERN", help_text
        )

    def test_help_surface_documents_canonical_command_or_category_discovery(self):
        root = Path(__file__).resolve().parents[1]
        help_text = (root / "plugins/system/help.py").read_text(encoding="utf-8")
        self.assertIn(".help <command-or-category>", help_text)

    def test_legacy_command_surface_is_a_hard_compatibility_baseline(self):
        legacy = {\n            "ai",\n            "aidiag",\n            "aijob",\n            "aria",\n            "ask",\n            "autopost",\n            "code",\n            "compress",\n            "explain",\n            "extract",\n            "ff",\n            "ocr",\n            "rclone",\n            "reverse",\n            "rewrite",\n            "rip",\n            "round",\n            "ss",\n            "summarize",\n            "transcribe",\n            "translate",\n            "archive",\n            "autorule",\n            "autostatus",\n            "backup",\n            "intel",\n            "case",\n            "ct",\n            "domainintel",\n            "gitintel",\n            "idn",\n            "linkintel",\n            "mediaintel",\n            "mediasim",\n            "reputation",\n            "secrisk",\n            "tgintel",\n            "userintel",\n            "ban",\n            "lockdown",\n            "modreport",\n            "mute",\n            "pin",\n            "unban",\n            "unmute",\n            "unpin",\n            "warn",\n            "warnings",\n            "dns",\n            "headers",\n            "ip",\n            "mediaflow",\n            "osint",\n            "portscan",\n            "qdel",\n            "qget",\n            "qlist",\n            "qnote",\n            "speedtest",\n            "bookmark",\n            "bookmarks",\n            "delremind",\n            "filter",\n            "remind",\n            "reminders",\n            "tdel",\n            "template",\n            "tget",\n            "tlist",\n            "unbookmark",\n            "allow",\n            "approve",\n            "arch",\n            "block",\n            "clone",\n            "delnote_sec",\n            "disallow",\n            "disapprove",\n            "getnote",\n            "hash",\n            "idbackup",\n            "listallowed",\n            "listdisallowed",\n            "logger",\n            "mirror",\n            "passgen",\n            "pmpermit",\n            "read",\n            "revert",\n            "savenote",\n            "savevo",\n            "setlogger",\n            "track",\n            "unblock",\n            "vault",\n            "afk",\n            "cache",\n            "cancel",\n            "cleancache",\n            "demote",\n            "diagnostics",\n            "doctor",\n            "eval",\n            "flags",\n            "ghost",\n            "health",\n            "help",\n            "job",\n            "jobs",\n            "kickme",\n            "mock",\n            "ops",\n            "owo",\n            "ping",\n            "plugins",\n            "promote",\n            "purge",\n            "purgeme",\n            "reindex",\n            "retry",\n            "search",\n            "shrug",\n            "slow",\n            "spam",\n            "stats",\n            "status",\n            "sysinfo",\n            "tasks",\n            "testall",\n            "tgcap",\n            "tgsync",\n            "update",\n            "zombies",\n            "bulkdel",\n            "chatdiag",\n            "entity",\n            "id",\n            "inspect",\n            "link",\n            "msg",\n            "ref",\n            "reply",\n            "b64",\n            "head",\n            "jsonfmt",\n            "rss",\n            "sha256",\n            "timestamp",\n            "urlencode",\n            "uuid",\n        }\n        self.assertEqual(len(legacy), 150)
        root = Path(__file__).resolve().parents[1]
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (root / "plugins").rglob("*.py")
        )
        missing = sorted(f".{name}" for name in legacy if f".{name}" not in source)
        self.assertEqual(
            missing, [], f"Legacy commands missing from plugin source: {missing}"
        )

    def test_help_deck_preserves_concrete_names_from_grouped_registrations(self):
        from plugins.system.help import _command_deck_rows

        grouped_registration = CommandRegistration(
            registration_id="grouped-id",
            pattern=r"^\.(alpha|beta)(?:\s+(.*))?$",
            handler=lambda event: None,
            category="system",
            description="grouped commands",
            aliases=("gamma",),
        )
        exposed, grouped = _command_deck_rows([grouped_registration])
        self.assertEqual(exposed, 3)
        self.assertEqual(grouped["system"], [".alpha", ".beta", ".gamma"])


if __name__ == "__main__":
    unittest.main()
