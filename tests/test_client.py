import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ASTRA_API_ID", "1")
os.environ.setdefault("ASTRA_API_HASH", "test-api-hash")
os.environ.setdefault("ASTRA_OWNER_ID", "1")

import client


class ClientSessionHardeningTests(unittest.TestCase):
    def test_create_client_disables_telethon_entity_persistence(self):
        class FakeSession:
            save_entities = True

        class FakeTelegramClient:
            def __init__(self, *args, **kwargs):
                self.session = FakeSession()

        with patch.object(client, "TelegramClient", FakeTelegramClient):
            created = client.create_client()

        self.assertFalse(created.session.save_entities)


if __name__ == "__main__":
    unittest.main()
