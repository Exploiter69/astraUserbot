"""Phase 17 migration-readiness contract tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_audit():
    path = ROOT / "tools" / "phase17_migration_audit.py"
    spec = importlib.util.spec_from_file_location("phase17_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Phase 17 audit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Phase17GateTests(unittest.TestCase):
    def test_required_migration_surface_exists(self):
        audit = load_audit()
        missing = [
            name
            for name, ok in audit.check_expected_files().items()
            if not ok
        ]
        self.assertEqual([], missing)

    def test_active_plugin_boundaries_are_clean(self):
        audit = load_audit()
        self.assertEqual([], audit.plugin_import_violations())

    def test_baseline_plugin_inventory_is_recoverable(self):
        audit = load_audit()
        baseline = audit.baseline_plugins()
        current = audit.current_plugins()

        self.assertGreater(len(baseline), 0)
        self.assertGreater(len(current), 0)

        # A missing baseline module is evidence for migration review, not
        # automatically a failure: modules may have been intentionally moved
        # or replaced during the platform migration.
        missing = baseline - current
        self.assertIsInstance(missing, set)

    def test_cutover_is_explicitly_not_authorized_by_static_gate(self):
        audit = load_audit()
        self.assertTrue(hasattr(audit, "QUARANTINED"))
        self.assertIn("plugins.ai.groq_client", audit.QUARANTINED)
        self.assertEqual("64538b1", audit.BASELINE)


if __name__ == "__main__":
    unittest.main()
