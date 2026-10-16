"""Check README documentation references and the runtime plugin inventory."""

from __future__ import annotations

import importlib
import re
import sys
from typing import get_args
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.plugins.manager import PluginManager


_COUNT_RE = re.compile(r"Current verified active-plugin inventory:\s*\*\*(\d+) active")


def runtime_active_plugin_count(root: Path = ROOT) -> int:
    """Use the same discovery rules as the runtime PluginManager."""
    manager = PluginManager(object(), root / "plugins")
    return len(manager.discover())


def validate_docs(root: Path, active_count: int) -> list[str]:
    findings: list[str] = []
    readme_path = root / "README.md"
    architecture_path = root / "docs" / "architecture" / "ARCHITECTURE.md"
    if not readme_path.is_file():
        return ["README.md is missing"]
    if not architecture_path.is_file():
        return ["docs/architecture/ARCHITECTURE.md is missing"]

    readme = readme_path.read_text(encoding="utf-8")
    architecture = architecture_path.read_text(encoding="utf-8")

    # README must not freeze a separately maintained inventory number.
    if re.search(r"\b\d+\s+active plugins?\b", readme, re.IGNORECASE):
        findings.append("README.md hard-codes an active plugin count; use runtime discovery")

    for destination in re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme):
        if destination.startswith(("https://", "http://", "mailto:")):
            continue
        local_path = destination.split("#", 1)[0]
        if not local_path:
            continue
        if not (root / local_path).is_file():
            findings.append(f"README.md references missing path: {local_path}")

    match = _COUNT_RE.search(architecture)
    if not match:
        findings.append("ARCHITECTURE.md has no canonical active-plugin inventory count")
    elif int(match.group(1)) != active_count:
        findings.append(
            f"ARCHITECTURE.md count is {match.group(1)} but PluginManager discovers {active_count}"
        )
    return findings


def main() -> int:
    count = runtime_active_plugin_count()
    findings = validate_docs(ROOT, count)
    print(f"runtime_active_plugins: {count}")
    if findings:
        for finding in findings:
            print(f"FAIL: {finding}")
        print("DOCS_CHECK_FAIL")
        return 1
    print("DOCS_CHECK_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
