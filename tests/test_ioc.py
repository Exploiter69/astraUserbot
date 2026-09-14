import unittest

from core.services.ioc import extract, normalize


class IOCExtractionTests(unittest.TestCase):
    def test_extracts_and_deduplicates_common_indicators(self):
        text = "Visit HTTPS://Example.COM/path?q=1 and https://example.com/path?q=1; email A@Example.COM, @Alice, CVE-2026-12345, 192.0.2.1 and 192.0.2.1."
        values = {(item.type, item.value) for item in extract(text)}
        self.assertIn(("URL", "https://example.com/path?q=1"), values)
        self.assertIn(("EMAIL", "a@example.com"), values)
        self.assertIn(("USERNAME", "alice"), values)
        self.assertIn(("CVE", "CVE-2026-12345"), values)
        self.assertIn(("IP", "192.0.2.1"), values)

    def test_hash_algorithms_are_explicit(self):
        self.assertTrue(normalize("HASH", "A" * 32).startswith("MD5:"))
        self.assertTrue(normalize("HASH", "B" * 64).startswith("SHA256:"))

    def test_invalid_ip_is_rejected(self):
        self.assertIsNone(normalize("IP", "999.999.999.999"))

    def test_extraction_is_bounded(self):
        text = " ".join(f"user{i}@example.com" for i in range(1000))
        self.assertLessEqual(len(extract(text)), 256)
