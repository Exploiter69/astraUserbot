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


def validate_sdk_docs(root: Path) -> list[str]:
    """Validate the public SDK export set against PLUGIN_SDK.md."""
    findings: list[str] = []
    doc_path = root / "PLUGIN_SDK.md"
    if not doc_path.is_file():
        return ["PLUGIN_SDK.md is missing"]
    try:
        sdk = importlib.import_module("astra.sdk")
    except Exception as exc:  # noqa: BLE001 - report import failure as a finding
        return [f"astra.sdk cannot be imported: {type(exc).__name__}: {exc}"]

    exports = getattr(sdk, "__all__", None)
    if not isinstance(exports, (list, tuple)) or not exports:
        return ["astra.sdk.__all__ must be a non-empty list or tuple"]
    if len(exports) != len(set(exports)):
        findings.append("astra.sdk.__all__ contains duplicate names")
    for name in exports:
        if not isinstance(name, str) or not hasattr(sdk, name):
            findings.append(f"astra.sdk.__all__ declares unresolved symbol: {name}")

    docs = doc_path.read_text(encoding="utf-8")
    version_match = re.search(r"SDK_API_VERSION:\s*`?([^\s`]+)`?", docs)
    if not version_match:
        findings.append("PLUGIN_SDK.md does not document SDK_API_VERSION")
    elif version_match.group(1) != sdk.SDK_API_VERSION:
        findings.append(
            f"PLUGIN_SDK.md SDK_API_VERSION is {version_match.group(1)} "
            f"but implementation is {sdk.SDK_API_VERSION}"
        )

    api_match = re.search(
        r"^##\s+[^\n]*API Reference[^\n]*\n(.*?)(?=^##\s+|\Z)",
        docs,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    if not api_match:
        findings.append("PLUGIN_SDK.md has no API Reference section")
        documented: set[str] = set()
    else:
        documented = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", api_match.group(1)))
    for name in sorted(documented - set(exports)):
        findings.append(f"PLUGIN_SDK.md documents symbol not exported by astra.sdk: {name}")
    for name in sorted(set(exports) - documented):
        findings.append(f"astra.sdk export missing from PLUGIN_SDK.md API Reference: {name}")
    return findings


def main() -> int:
    count = runtime_active_plugin_count()
    findings = validate_docs(ROOT, count)
    findings.extend(validate_sdk_docs(ROOT))
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
