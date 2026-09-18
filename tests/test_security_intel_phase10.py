from __future__ import annotations

import json
import unittest

from core.services.security_intel import SecurityIntelService


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self.text = json.dumps(payload)


class FakeHttp:
    def __init__(self):
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "urlhaus" in url:
            return FakeResponse(200, {"query_status": "ok", "url_status": "online", "threat": "malware"})
        return FakeResponse(200, {"query_status": "ok", "data": [{"signature": "test-family", "first_seen": "2026-01-01", "file_type": "ELF"}]})


class FakePublicIntel:
    async def link_intel(self, target):
        return {"rows": ["Redirect hops: 3", "  1. https://a.example", "  2. https://b.example", "  3. https://c.example"]}


class SecurityIntelPhase10Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.http = FakeHttp()
        self.service = SecurityIntelService(self.http, FakePublicIntel())

    def test_idn_reports_punycode_and_mixed_script(self):
        result = self.service.analyze_idn("xn--80ak6aa92e.com")
        self.assertTrue(result.punycode)
        self.assertIn("Cyrillic", result.scripts)

    def test_idn_plain_ascii_is_not_mixed(self):
        result = self.service.analyze_idn("example.com")
        self.assertFalse(result.punycode)
        self.assertFalse(result.mixed_script)
        self.assertEqual(result.ascii, "example.com")

    def test_message_url_extraction_is_bounded(self):
        text = " ".join(f"https://example{i}.test/path" for i in range(10))
        self.assertEqual(len(self.service.extract_urls(text)), 3)

    async def test_message_risk_uses_extracted_urls(self):
        result = await self.service.assess_text("See https://example.test/login")
        self.assertEqual(len(result["assessments"]), 1)
        self.assertEqual(result["assessments"][0].target, "https://example.test/login")

    async def test_url_risk_is_bounded_and_explainable(self):
        result = await self.service.assess_url("http://xn--80ak6aa92e.com/login")
        self.assertGreaterEqual(result.score, 30)
        self.assertLessEqual(result.score, 100)
        self.assertEqual(result.level, "HIGH")
        self.assertTrue(any("Punycode" in item for item in result.signals))
        self.assertTrue(any("redirect" in item.lower() for item in result.signals))

    async def test_urlhaus_adapter_minimizes_result(self):
        result = await self.service.reputation_urlhaus("https://example.test")
        self.assertEqual(result["status"], "FOUND")
        self.assertNotIn("raw", result)
        self.assertEqual(len(self.http.calls), 1)

    async def test_malwarebazaar_adapter_minimizes_result(self):
        result = await self.service.reputation_hash("a" * 64)
        self.assertEqual(result["status"], "FOUND")
        self.assertEqual(result["signature"], "test-family")
        self.assertNotIn("raw", result)

    async def test_hash_validation_rejects_unbounded_input(self):
        with self.assertRaises(ValueError):
            await self.service.reputation_hash("not-a-hash")

    async def test_inspect_dispatches_url_and_hash(self):
        url_result = await self.service.inspect("https://example.test/login")
        hash_result = await self.service.inspect("b" * 64)
        self.assertEqual(url_result["kind"], "url")
        self.assertEqual(hash_result["kind"], "hash")


if __name__ == "__main__":
    unittest.main()
