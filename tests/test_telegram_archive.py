import unittest

from core.services.telegram_archive import TelegramArchiveJobModel, TelegramArchiveRequest


class TelegramArchiveJobModelTests(unittest.TestCase):
    def test_request_is_bounded_and_deterministic(self):
        request = TelegramArchiveJobModel.request("chat:1", limit=250, min_message_id=42, include_media=True)
        self.assertEqual(request.payload["limit"], 250)
        self.assertEqual(request.payload["min_message_id"], 42)
        self.assertTrue(request.payload["include_media"])
        self.assertEqual(request.idempotency_key, TelegramArchiveRequest("chat:1", 250, 42, True).idempotency_key)

    def test_enqueue_contract_targets_durable_job_engine(self):
        request = TelegramArchiveJobModel.request("@example", limit=100)
        kwargs = TelegramArchiveJobModel.enqueue_kwargs(request)
        self.assertEqual(kwargs["job_type"], "TELEGRAM_ARCHIVE")
        self.assertEqual(kwargs["priority"], 4)
        self.assertEqual(kwargs["resource_class"], "telegram_archive")
        self.assertEqual(kwargs["payload"]["schema_version"], 1)
        self.assertEqual(kwargs["idempotency_key"], request.idempotency_key)

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            TelegramArchiveJobModel.request("chat:1", limit=0)
        with self.assertRaises(ValueError):
            TelegramArchiveJobModel.request("chat:1", limit=501)
        with self.assertRaises(ValueError):
            TelegramArchiveJobModel.request("chat:1", min_message_id=-1)

    def test_request_type_is_required_for_enqueue_contract(self):
        with self.assertRaises(TypeError):
            TelegramArchiveJobModel.enqueue_kwargs({})
