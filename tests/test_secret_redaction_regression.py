"""Regression coverage for main.SecretFilter without importing runtime side effects."""

from __future__ import annotations

import ast
import logging
import math
import random
import re
from pathlib import Path

import pytest


def _load_secret_filter_namespace():
    # Importing main.py configures root handlers and creates data/logs. Extract
    # only the filter class (and later its helper) to avoid runtime side effects.
    source_path = Path(__file__).resolve().parents[1] / "main.py"
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    nodes = [
        node
        for node in module_ast.body
        (isinstance(node, ast.ClassDef) and node.name == "SecretFilter") or (isinstance(node, ast.FunctionDef) and node.name == "_has_high_entropy_and_diversity")
    ]
    isolated_module = ast.Module(body=nodes, type_ignores=[])
    namespace = {"re": re, "logging": logging, "math": math}
    exec(compile(isolated_module, str(source_path), "exec"), namespace)
    return namespace


def _filter_message(message: str) -> str:
    secret_filter = _load_secret_filter_namespace()["SecretFilter"]()
    record = logging.LogRecord(
        name="phase3a.redaction.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    assert secret_filter.filter(record)
    return record.getMessage()


def _synthetic_session() -> str:
    """Reproducible, synthetic session-shaped data; never a real credential."""
    rng = random.Random(20261015)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    return "1" + "".join(rng.choice(alphabet) for _ in range(349))


@pytest.mark.parametrize(
    ("label", "message", "secret"),
    [
        pytest.param(
            "raw_telethon_session_string",
            "Telethon client restored: " + _synthetic_session(),
            _synthetic_session(),
            marks=pytest.mark.xfail(
                strict=True,
                reason="SecretFilter does not recognize an unlabeled raw Telethon StringSession.",
            ),
        ),
        (
            "api_hash",
            "configuration rejected: API_HASH=synthetic_api_hash_0123456789",
            "synthetic_api_hash_0123456789",
        ),
        pytest.param(
            "vault_plaintext",
            "vault plaintext: synthetic-vault-plaintext-value",
            "synthetic-vault-plaintext-value",
            marks=pytest.mark.xfail(
                strict=True,
                reason="SecretFilter does not recognize vault plaintext context.",
            ),
        ),
        pytest.param(
            "bearer_token",
            "upstream response included Bearer synthetic_bearer_token_value",
            "synthetic_bearer_token_value",
            marks=pytest.mark.xfail(
                strict=True,
                reason="SecretFilter does not recognize a standalone Bearer credential.",
            ),
        ),
        pytest.param(
            "multiline_secret_on_second_line",
            "worker started successfully\n1AABCD9876secondLineSyntheticSession",
            "1AABCD9876secondLineSyntheticSession",
            marks=pytest.mark.xfail(
                strict=True,
                reason="SecretFilter leaves an unlabeled credential on a later line unchanged.",
            ),
        ),
    ],
)
def test_sensitive_values_are_redacted_from_log_messages(label, message, secret):
    filtered = _filter_message(message)
    assert secret not in filtered, f"{label} leaked through SecretFilter: {filtered!r}"


def test_short_alphanumeric_session_lookalike_is_not_redacted():
    near_match = "1A" + "B7cD9eF2gH4jK6mN8pQ0rS1tU3vW5xY"
    assert len(near_match) == 37
    assert _filter_message(f"diagnostic id {near_match}") == f"diagnostic id {near_match}"


def test_order_id_with_session_like_prefix_is_not_redacted():
    message = "Processed order 1AABCD1234 successfully."
    assert _filter_message(message) == message


def test_high_entropy_non_base64_urlsafe_text_is_not_a_session():
    non_session = "A9z!K2@qL7#vP4$rT8%wX1^bN6&cM3*eF0+"
    message = f"customer note: {non_session}"
    assert _filter_message(message) == message


def test_benign_message_is_untouched_end_to_end():
    message = "Worker started successfully; processed 12 records in 0.42 seconds."
    assert _filter_message(message) == message


def test_benign_text_on_second_line_survives():
    message = "worker started successfully\nsecond line contains ordinary status text"
    assert _filter_message(message) == message



@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1" + "".join(random.Random(7).choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-") for _ in range(349)), True),
        ("A" * 350, False),
        ("AB" * 175, False),
        ("short", False),
    ],
)
def test_entropy_and_diversity_helper(value, expected):
    helper = _load_secret_filter_namespace()["_has_high_entropy_and_diversity"]
    assert helper(value) is expected
