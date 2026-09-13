import asyncio

from telethon import types

import plugins.media.autopost as autopost


def test_autopost_persists_user_peer_access_hash():
    peer = types.InputPeerUser(user_id=123, access_hash=456)
    assert autopost._peer_metadata(peer) == ("user", 456)
    rebuilt = autopost._input_peer(123, "user", 456)
    assert isinstance(rebuilt, types.InputPeerUser)
    assert rebuilt.user_id == 123
    assert rebuilt.access_hash == 456


def test_autopost_persists_channel_peer_access_hash():
    peer = types.InputPeerChannel(channel_id=123, access_hash=456)
    assert autopost._peer_metadata(peer) == ("channel", 456)
    rebuilt = autopost._input_peer(123, "channel", 456)
    assert isinstance(rebuilt, types.InputPeerChannel)
    assert rebuilt.channel_id == 123
    assert rebuilt.access_hash == 456


def test_autopost_worker_uses_persisted_peer_identity():
    class FakeDB:
        async def fetchall(self, _query):
            return [(7, 123, "hello", "user", 456)]

    class FakeClient:
        def __init__(self):
            self.targets = []

        async def send_message(self, target, message):
            self.targets.append((target, message))

    async def scenario():
        old_db = autopost.db
        old_client = autopost._client
        client = FakeClient()
        autopost.db = FakeDB()
        autopost._client = client
        try:
            await autopost.autopost_worker()
        finally:
            autopost.db = old_db
            autopost._client = old_client

        assert len(client.targets) == 1
        target, message = client.targets[0]
        assert isinstance(target, types.InputPeerUser)
        assert target.user_id == 123
        assert target.access_hash == 456
        assert message == "hello"

    asyncio.run(scenario())
