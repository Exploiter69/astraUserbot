"""Characterize gaps in main.SecretFilter without importing runtime side effects."""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import pytest


def _load_secret_filter_without_importing_main():
    # Importing main.py configures root handlers and creates data/logs. Extracting
    # only the class AST lets this test exercise the real filter without touching
    # runtime artifacts or requiring Telegram credentials.
    source_path = Path(__file__).resolve().parents[1] / "main.py"
    module_ast = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    class_node = next(
        node
        for node in module_ast.body
        if isinstance(node, ast.ClassDef) and node.name == "SecretFilter"
    )
    isolated_module = ast.Module(body=[class_node], type_ignores=[])
    namespace = {"re": re, "logging": logging}
    exec(compile(isolated_module, str(source_path), "exec"), namespace)
    return namespace["SecretFilter"]


SecretFilter = _load_secret_filter_without_importing_main()


def _filter_message(message: str) -> str:
    record = logging.LogRecord(
        name="phase1.redaction.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    assert SecretFilter().filter(record)
    return record.getMessage()


@pytest.mark.parametrize(
    ("label", "message", "secret"),
    [
        pytest.param(
            "telethon_session_string",
            "session restored: 1AABCD1234syntheticTelethonSessionString",
            "1AABCD1234syntheticTelethonSessionString",
            marks=pytest.mark.xfail(
                strict=True,
                reason="SecretFilter only redacts labeled key/value patterns; a raw Telethon session string is not recognized.",
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
                reason="SecretFilter does not identify unlabeled vault plaintext in free-form log messages.",
            ),
        ),
        pytest.param(
            "bearer_token",
            "upstream response included Bearer synthetic_bearer_token_value",
            "synthetic_bearer_token_value",
            marks=pytest.mark.xfail(
                strict=True,
                reason="SecretFilter does not recognize a standalone Bearer credential without an Authorization key label.",
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
