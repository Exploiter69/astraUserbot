"""Phase 18 production hardening contract tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_audit():
    path = ROOT / "tools" / "phase18_production_audit.py"
    spec = importlib.util.spec_from_file_location("phase18_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Phase 18 audit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Phase18HardeningGateTests(unittest.TestCase):
    def test_current_plugin_inventory_is_nonempty_and_quarantine_is_explicit(self):
        audit = load_audit()
        plugins = audit.current_plugins()
        self.assertGreater(len(plugins), 0)
        self.assertIn("plugins.ai.groq_client", audit.QUARANTINED)

    def test_command_audit_has_no_invalid_permissions_or_parse_errors(self):
        audit = load_audit()
        result = audit.command_audit()
        self.assertEqual([], result["invalid_permissions"])
        self.assertEqual([], result["parse_errors"])
        self.assertTrue(result["command_router_is_outgoing_only"])
        self.assertGreater(result["registry_registrations"], 0)

    def test_resource_contracts_are_present(self):
        audit = load_audit()
        result = audit.resource_contract()
        self.assertTrue(all(result["checks"].values()), result["checks"])
        self.assertGreater(result["details"]["http_default_response_bytes"], 0)
        self.assertGreater(result["details"]["subprocess_default_output_bytes"], 0)
        self.assertGreater(result["details"]["media_max_workspace_bytes"], 0)

    def test_shutdown_audit_requires_runtime_gate(self):
        audit = load_audit()
        result = audit.shutdown_audit()
        self.assertTrue(result["context_closes_jobs_as_service"])
        self.assertTrue(result["job_close_has_unbounded_gather"])
        self.assertTrue(result["runtime_gate_required"])


if __name__ == "__main__":
    unittest.main()
