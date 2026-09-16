from __future__ import annotations

import unittest

from core.services.automation import AutomationEngine, AutomationError


class AutomationTriggerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = AutomationEngine(None, None, None, owner_id=1)

    def test_message_matchers_are_deterministic_and_bounded(self):
        event = {"event_type": "MESSAGE_NEW", "source_peer": "1", "entity_id": 7, "payload": {"text": "Hello Astra", "has_media": True}}
        self.assertTrue(self.engine._match_matches({"contains": "astra"}, event))
        self.assertTrue(self.engine._match_matches({"prefix": "hello"}, event))
        self.assertTrue(self.engine._match_matches({"has_media": True}, event))
        self.assertTrue(self.engine._match_matches({"sender_id": 7}, event))
        self.assertFalse(self.engine._match_matches({"equals": "nope"}, event))

    def test_all_roadmap_trigger_types_are_declared(self):
        self.assertEqual(
            self.engine.__class__.__module__,
            "core.services.automation",
        )
        self.assertTrue({"MESSAGE_NEW", "MESSAGE_EDIT", "MEDIA_OBSERVED", "SCHEDULED", "JOB_COMPLETED", "INTELLIGENCE_OBSERVED", "OWNER_COMMAND"} <= __import__("core.services.automation", fromlist=["TRIGGERS"]).TRIGGERS)

    def test_scheduled_rule_requires_positive_timestamp(self):
        with self.assertRaises(AutomationError):
            self.engine._validate_rule({"type": "SCHEDULED", "at": 0}, {"owner": "1"}, {}, [{"type": "TAG", "tag": "x"}], 0, 0)

    def test_explicit_scope_is_required_even_for_owner_command(self):
        with self.assertRaises(AutomationError):
            self.engine._validate_rule({"type": "OWNER_COMMAND"}, {}, {}, [{"type": "TAG", "tag": "x"}], 0, 0)
