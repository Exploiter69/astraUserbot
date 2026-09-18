from __future__ import annotations

import unittest

from tools.plugin_registry import build_registry, validate_registry


class Phase10RegistryTests(unittest.TestCase):
    def test_registry_is_bounded_and_compatible(self):
        rows = build_registry()
        self.assertLessEqual(len(rows), 512)
        self.assertTrue(rows)
        self.assertEqual(validate_registry(rows), [])

    def test_registry_contains_security_plugin_capabilities(self):
        rows = build_registry()
        item = next(row for row in rows if row["module"] == "plugins.intelligence.security_intel")
        self.assertIn("network.request", item["capabilities"])
        self.assertEqual(item["api_version"], 1)


if __name__ == "__main__":
    unittest.main()
