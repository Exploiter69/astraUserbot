import inspect
import unittest

from plugins.media import aria2
from plugins.media import ffmpeg
from plugins.media import rclone
from plugins.media_ops import speech
from plugins.media_ops import stream
from core.services import logger as logger_service
from plugins.security import logger as logger_plugin


class FakeRetentionDB:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, params=()):
        self.calls.append((sql, params))


class Phase6GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_and_subprocess_migrations_have_cleanup_or_isolation(self):
        self.assertIn("create_workspace", inspect.getsource(stream.handle_rip))
        self.assertIn("finally:", inspect.getsource(stream.handle_rip))
        self.assertIn("finally:", inspect.getsource(aria2.handle_aria))
        self.assertIn("subprocess", inspect.getsource(aria2.handle_aria))
        self.assertIn("subprocess", inspect.getsource(rclone.handle_rclone))
        self.assertIn("finally:", inspect.getsource(ffmpeg.handle_ffmpeg))
        self.assertIn("finally:", inspect.getsource(speech.handle_speech))


if __name__ == "__main__":
    unittest.main()
