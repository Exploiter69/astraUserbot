"""Read-only Phase 10 audit for security intelligence and plugin ecosystem."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def module_assignments(tree: ast.Module) -> dict[str, object]:
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        result[target.id] = ast.literal_eval(node.value)
                    except Exception:
                        pass
    return result


def main() -> int:
    service = ROOT / "core/services/security_intel.py"
    plugin = ROOT / "plugins/intelligence/security_intel.py"
    registry = ROOT / "tools/plugin_registry.py"
    matrix = ROOT / "docs/COMPETITOR_FEATURE_MATRIX.md"
    phase = ROOT / "docs/PHASE_10_SECURITY_ECOSYSTEM.md"

    required = [service, plugin, registry, matrix, phase]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        print("PHASE10_AUDIT_FAIL")
        print("missing:", ", ".join(missing))
        return 1

    service_tree = parse(service)
    plugin_tree = parse(plugin)
    registry_tree = parse(registry)
    plugin_meta = module_assignments(plugin_tree)

    required_methods = {"analyze_idn", "assess_url", "reputation_urlhaus", "reputation_hash", "inspect"}
    methods = {
        node.name
        for node in service_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SecurityIntelService"
        for node in node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing_methods = sorted(required_methods - methods)

    has_commands = all(name in plugin_meta for name in ("plugin_name", "plugin_version", "plugin_api_version", "capabilities"))
    has_setup = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "setup" for node in plugin_tree.body)
    registry_has_ast = any(isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "parse" for node in registry_tree.body for _ in [node])

    payload = {
        "security_service": "PASS" if not missing_methods else "FAIL",
        "plugin_metadata": "PASS" if has_commands else "FAIL",
        "plugin_setup": "PASS" if has_setup else "FAIL",
        "registry_ast": "PASS" if registry_has_ast else "FAIL",
        "competitor_matrix": "PASS" if matrix.exists() else "FAIL",
        "missing_methods": missing_methods,
    }
    ok = all(value == "PASS" for key, value in payload.items() if key != "missing_methods")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print("PHASE10_SECURITY_ECOSYSTEM_AUDIT_PASS" if ok else "PHASE10_SECURITY_ECOSYSTEM_AUDIT_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
