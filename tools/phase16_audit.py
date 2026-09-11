from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins"

QUARANTINED = {
    "plugins.ai.ask",
    "plugins.ai.summarize",
    "plugins.ai.transcribe",
    "plugins.ai.groq_client",
}

FORBIDDEN_IMPORTS = {
    "requests",
    "httpx",
    "urllib.request",
    "subprocess",
    "aiohttp",
    "helpers.shell",
    "helpers.net",
}


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def main() -> int:
    active = []
    quarantined = []
    violations = []

    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue

        name = module_name(path)

        if name in QUARANTINED:
            quarantined.append(name)
            continue

        active.append(name)

        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{name}: syntax error: {exc}")
            continue

        imports = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

        for forbidden in sorted(FORBIDDEN_IMPORTS):
            if forbidden in imports or any(
                item.startswith(forbidden + ".") for item in imports
            ):
                violations.append(
                    f"{name}: forbidden boundary import: {forbidden}"
                )

    print("=== PHASE 16 PLUGIN AUDIT ===")
    print(f"active_plugins: {len(active)}")
    print(f"quarantined_plugins: {len(quarantined)}")
    print(f"violations: {len(violations)}")

    if quarantined:
        print("--- quarantined ---")
        for name in quarantined:
            print(name)

    if violations:
        print("--- violations ---")
        for item in violations:
            print(item)
        return 1

    print("PHASE16_AUDIT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
