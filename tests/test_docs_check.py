from pathlib import Path

from tools.docs_check import validate_docs


def _write_fixture(root: Path, *, architecture_count: int = 3, missing_link: bool = False):
    (root / "docs" / "architecture").mkdir(parents=True)
    (root / "docs" / "roadmap").mkdir(parents=True)
    (root / "docs" / "roadmap" / "ROADMAP.md").write_text("# roadmap\n", encoding="utf-8")
    target = "docs/missing.md" if missing_link else "docs/roadmap/ROADMAP.md"
    (root / "README.md").write_text(
        f"[Roadmap]({target})\n\nThe inventory is discovered at runtime.\n",
        encoding="utf-8",
    )
    (root / "docs" / "architecture" / "ARCHITECTURE.md").write_text(
        f"Current verified active-plugin inventory: **{architecture_count} active, "
        "4 intentionally quarantined**.\n",
        encoding="utf-8",
    )


def test_docs_check_passes_when_links_and_runtime_count_match(tmp_path):
    _write_fixture(tmp_path)
    assert validate_docs(tmp_path, active_count=3) == []


def test_docs_check_fails_on_count_and_link_drift(tmp_path):
    _write_fixture(tmp_path, architecture_count=2, missing_link=True)
    findings = validate_docs(tmp_path, active_count=3)
    assert any("missing path: docs/missing.md" in finding for finding in findings)
    assert any("count is 2" in finding and "discovers 3" in finding for finding in findings)
