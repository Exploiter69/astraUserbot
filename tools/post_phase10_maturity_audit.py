from __future__ import annotations

"""Static post-Phase-10 A–H maturity audit.

This audit intentionally verifies architecture/contracts, not owner-host runtime
credentials, Telegram connectivity, external provider availability, or systemd.
Those remain local/live acceptance steps.
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "ROADMAP.md",
    "ROADMAP_COMPETITIVE_ADDENDUM.md",
    "ROADMAP_POST_PHASE10.md",
    "docs/POST_PHASE10_ACCEPTANCE.md",
    "docs/UNIFIED_SEARCH.md",
    "docs/ENTITY_INSPECTOR.md",
    "docs/FIRST_RUN.md",
    "core/registry.py",
    "core/services/search.py",
    "core/services/intel_correlation.py",
    "core/context.py",
    "plugins/system/help.py",
    "plugins/system_ops/platform.py",
    "plugins/system_ops/product_surface.py",
    "helpers/ux.py",
)

REQUIRED_TEXT = {
    "core/registry.py": (
        "operation_class",
        "required_capabilities",
        "examples",
        "compatibility",
        "source_ref",
        "find_registrations",
        "recent_registrations",
    ),
    "plugins/system/help.py": (
        ".command",
        "search|describe|examples|category|aliases|permissions|source|recent",
        ".help <command-or-category>",
    ),
    "core/services/search.py": (
        "class SearchPage",
        "search_page",
        "_encode_cursor",
        "_decode_cursor",
        '"ocr"',
        '"transcript"',
        '"case"',
        '"security"',
    ),
    "core/context.py": (
        'self.register("intelgraph"',
        'self.register("intel_correlation"',
        'self.register("search"',
    ),
    "plugins/system_ops/product_surface.py": (
        "inspect|correlate",
        "plugin",
        "aiux",
        "doctor|config|update|restart",
        "observed/derived/possible/unknown",
    ),
    "helpers/ux.py": (
        "list_buttons",
        "form_buttons",
        "gallery_buttons",
        "bounded_callback_token",
        "parse_callback_token",
    ),
    "docs/POST_PHASE10_ACCEPTANCE.md": (
        "Gate A",
        "Gate B",
        "Gate C",
        "Gate D",
        "Gate E",
        "Gate F",
        "Gate G",
        "Gate H",
    ),
}

def main() -> int:
    failures: list[str] = []

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            failures.append(f"missing file: {rel}")

    for rel, needles in REQUIRED_TEXT.items():
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                failures.append(f"{rel}: missing contract marker {needle!r}")

    registry = (ROOT / "core/registry.py").read_text(encoding="utf-8")
    if "raise CommandRegistrationError" not in registry:
        failures.append("registry: deterministic registration rejection missing")

    product = (ROOT / "plugins/system_ops/product_surface.py").read_text(encoding="utf-8")
    for marker in ("PLUGIN_PATTERN", "AI_PATTERN", "CONTROL_PATTERN"):
        if marker not in product:
            failures.append(f"product surface: missing {marker}")

    if failures:
        print("POST_PHASE10_MATURITY_AUDIT=FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("POST_PHASE10_MATURITY_AUDIT=PASS")
    print("Gates A-H: implementation contracts present")
    print("Owner-host/live validation: required separately")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
