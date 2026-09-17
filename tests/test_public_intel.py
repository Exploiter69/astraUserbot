import unittest

from core.registry import clear_registrations, list_registrations
from core.services.public_intel import PublicIntelService
from plugins.intelligence import public_sources


class FakeGraph:
    def __init__(self):
        self.entities = []
        self.observations = []
        self.relationships = []
        self.sources = []
        self._counter = 0

    async def add_source(self, **kwargs):
        self.sources.append(kwargs)

    async def add_entity(self, **kwargs):
        self._counter += 1
        entity_id = f"e{self._counter}"
        self.entities.append((entity_id, kwargs))
        return entity_id

    async def add_observation(self, **kwargs):
        self._counter += 1
        observation_id = f"o{self._counter}"
        self.observations.append((observation_id, kwargs))
        return observation_id

    async def add_relationship(self, **kwargs):
        self.relationships.append(kwargs)


class FakeResponse:
    def __init__(self, status=200, text="{}", headers=None, url="https://example.test"):
        self.status = status
        self.text = text
        self.headers = headers or {}
        self.url = url


class FakeHttp:
    def __init__(self):
        self.requests = []

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        if "github.com" in url:
            return FakeResponse(200, '[{"name":"repo","html_url":"https://github.com/example/repo"}]')
        if "gitlab.com/api/v4/users" in url:
            return FakeResponse(200, '[{"id":42,"username":"example"}]')
        if "gitlab.com/api/v4/users/42/projects" in url:
            return FakeResponse(200, '[{"name":"project","web_url":"https://gitlab.com/example/project"}]')
        if "reddit.com" in url:
            return FakeResponse(200, '{"data":{"name":"example"}}')
        return FakeResponse(404, "{}")

    async def head(self, url, **kwargs):
        self.requests.append(("HEAD", url, kwargs))
        return FakeResponse(302, "", {"Location": "https://example.test/final"}, url)


class FakeTelegram:
    async def get_entity(self, target):
        class Entity:
            id = 123
            username = "example"
            first_name = "Example"
            about = "Public profile https://example.test/profile"

        return Entity()


class FakeClient:
    def __init__(self):
        self.handlers = []

    def add_event_handler(self, handler, event_builder):
        self.handlers.append((handler, event_builder))

    def remove_event_handler(self, handler, event_builder):
        self.handlers = [item for item in self.handlers if item != (handler, event_builder)]


class PublicIntelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.graph = FakeGraph()
        self.http = FakeHttp()
        self.service = PublicIntelService(self.graph, self.http, FakeTelegram())

    def setUp(self):
        clear_registrations(FakeClient())

    async def test_username_pivot_is_bounded_and_evidence_backed(self):
        result = await self.service.username_pivot("@Example")
        self.assertEqual(result["target"], "example")
        self.assertLessEqual(len(result["findings"]), 3)
        self.assertEqual(len(self.graph.sources), 1)
        self.assertTrue(self.graph.observations)
        self.assertTrue(all(item[1]["source_family"] == "public_profile" for item in self.graph.observations))

    async def test_telegram_intel_records_bio_url_without_identity_inference(self):
        result = await self.service.telegram_intel("@Example")
        self.assertIn("@example", result["rows"][0])
        self.assertTrue(any(item[1]["entity_type"] == "URL" for item in self.graph.entities))
        self.assertTrue(all(item["relationship_type"] == "LINKS_TO" for item in self.graph.relationships))

    async def test_link_intel_stops_at_bounded_redirect_chain(self):
        result = await self.service.link_intel("https://example.test/start")
        self.assertIn("Redirect hops: 1", result["rows"])
        self.assertTrue(any(item[1]["entity_type"] == "DOMAIN" for item in self.graph.entities))

    async def test_command_registration_contains_all_phase_8_surfaces(self):
        client = FakeClient()
        await public_sources.setup(client)
        self.assertEqual(len(list_registrations()), 1)
        pattern = list_registrations()[0].pattern
        for name in ("tgintel", "userintel", "domainintel", "ct", "linkintel", "gitintel"):
            self.assertIn(name, pattern)
        clear_registrations(client)
        self.assertEqual(client.handlers, [])

    async def test_invalid_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            await self.service.username_pivot("bad username")
        with self.assertRaises(ValueError):
            await self.service.domain_intel("not a domain")
        with self.assertRaises(ValueError):
            await self.service.link_intel("ftp://example.test")


if __name__ == "__main__":
    unittest.main()
