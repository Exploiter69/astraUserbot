from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]


def _source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_productivity_plugin_has_durable_feature_surface():
    tree = ast.parse(_source("plugins/productivity.py"))
    registrations = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "register_cmd"]
    assert len(registrations) >= 10
    text = _source("plugins/productivity.py")
    for token in ("reminders", "bookmarks", "templates", "delremind", "unbookmark"):
        assert token in text


def test_productivity_bounds_are_explicit():
    text = _source("plugins/productivity.py")
    assert "_MAX_TEXT = 4000" in text
    assert "_MAX_NAME = 48" in text
    assert "_MAX_ROWS = 100" in text
    assert "5 <= seconds <= 30 * 86400" in text


def test_moderation_has_bounded_destructive_controls():
    text = _source("plugins/moderation.py")
    assert "_MAX_LOCKDOWN = 200" in text
    assert "_MAX_AUDIT = 5000" in text
    assert ".lockdown CONFIRM" in text
    assert "Cannot moderate the owner account." in text


def test_telegram_utilities_have_bounded_bulk_delete():
    text = _source("plugins/telegram_utils.py")
    assert "_MAX_BULK = 100" in text
    assert "1 <= count <= _MAX_BULK" in text
    assert "handle_inspect" in text
    assert "handle_chatdiag" in text
