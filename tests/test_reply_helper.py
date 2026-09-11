import unittest
from types import SimpleNamespace

from helpers.reply import get_text_and_media


class FakeMatch:
    def __init__(self, groups):
        self.groups = groups

    def group(self, index):
        if index < 1 or index > len(self.groups):
            raise IndexError("no such group")
        return self.groups[index - 1]


class FakeReply:
    def __init__(self, text=None, media=None):
        self.text = text
        self.media = media


class FakeEvent:
    def __init__(self, pattern_match=None, reply=None):
        self.pattern_match = pattern_match
        self.is_reply = reply is not None
        self._reply = reply

    async def get_reply_message(self):
        return self._reply


class ReplyHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_pattern_without_capture_group_is_safe(self):
        event = FakeEvent(
            pattern_match=FakeMatch([]),
            reply=FakeReply(media="image"),
        )

        text, media = await get_text_and_media(event)

        self.assertIsNone(text)
        self.assertEqual(media, "image")

    async def test_capture_group_is_preserved(self):
        event = FakeEvent(
            pattern_match=FakeMatch(["hello"]),
            reply=FakeReply(media="image"),
        )

        text, media = await get_text_and_media(event)

        self.assertEqual(text, "hello")
        self.assertEqual(media, "image")

    async def test_reply_text_is_used_when_command_has_no_text(self):
        event = FakeEvent(
            pattern_match=FakeMatch([]),
            reply=FakeReply(text="text from reply"),
        )

        text, media = await get_text_and_media(event)

        self.assertEqual(text, "text from reply")
        self.assertIsNone(media)


if __name__ == "__main__":
    unittest.main()
