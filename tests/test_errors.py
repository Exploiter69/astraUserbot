import unittest

from core.errors import (
    AstraError,
    AuthorizationError,
    CommandError,
    ErrorCode,
    TimeoutError,
    as_astra_error,
    user_message,
)


class ErrorTests(unittest.TestCase):
    def test_controlled_error_has_stable_code_and_safe_message(self):
        error = AuthorizationError()
        self.assertEqual(error.code, ErrorCode.AUTHORIZATION)
        self.assertEqual(
            user_message(error),
            "You are not authorized to perform this operation.",
        )

    def test_command_error_preserves_explicit_safe_message(self):
        error = CommandError("Invalid command argument.")
        self.assertEqual(error.code, ErrorCode.VALIDATION)
        self.assertEqual(user_message(error), "Invalid command argument.")

    def test_unexpected_exception_is_wrapped_without_using_exception_text(self):
        original = RuntimeError("/secret/provider/token=abc123")
        error = as_astra_error(
            original,
            operation="media.convert",
            component="media",
            correlation_id="abc123def456",
        )
        self.assertIsInstance(error, AstraError)
        self.assertEqual(error.code, ErrorCode.UNKNOWN)
        self.assertEqual(error.context.operation, "media.convert")
        self.assertEqual(error.context.component, "media")
        self.assertEqual(error.context.correlation_id, "abc123def456")
        self.assertNotIn("secret", user_message(error))
        self.assertNotIn("abc123", user_message(error))
        self.assertIs(error.cause, original)

    def test_timeout_is_retryable(self):
        error = TimeoutError()
        self.assertEqual(error.code, ErrorCode.TIMEOUT)
        self.assertTrue(error.retryable)
        self.assertTrue(error.context.retryable)

    def test_messages_are_bounded(self):
        error = CommandError("x" * 1000)
        self.assertEqual(len(user_message(error)), 500)


if __name__ == "__main__":
    unittest.main()
