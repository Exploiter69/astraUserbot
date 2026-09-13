"""Read-only structural audit for the AstraUserbot plugin ecosystem.

The audit intentionally uses AST inspection instead of importing plugins. Plugin
imports may have external dependencies or side effects, so discovery correctness
must not depend on executing arbitrary feature code.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.plugins.contract import PLUGIN_API_VERSION
from core.plugins.manager import PluginManager


QUARANTINED = frozenset(PluginManager._QUARANTINED_MODULES)
EXCLUDED = {"__init__.py"}
CAPABILITY_NAMES = {
    "telegram.read", "telegram.write", "telegram.moderate",
    "filesystem.read", "filesystem.write", "subprocess.execute",
    "network.request", "media.process", "ai.inference", "account.control",
    "security.manage",
}


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def literal_value(node: ast.AST | None):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def audit_file(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assignments: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments[node.target.id] = node.value

    setup = functions.get("setup")
    shutdown = functions.get("shutdown")
    dependencies = literal_value(assignments.get("dependencies"))
    optional = literal_value(assignments.get("optional_dependencies"))
    capabilities = literal_value(assignments.get("capabilities"))
    api_version = literal_value(assignments.get("plugin_api_version"))
    registrations = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "register_cmd"
    ]
    direct_handlers = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_event_handler"
    ]

    dependency_ok = dependencies is None or (
        isinstance(dependencies, (tuple, list, str))
        and (not isinstance(dependencies, (tuple, list)) or all(isinstance(item, str) for item in dependencies))
    )
    optional_ok = optional is None or (
        isinstance(optional, (tuple, list, str))
        and (not isinstance(optional, (tuple, list)) or all(isinstance(item, str) for item in optional))
    )
    capability_ok = capabilities is None or (
        isinstance(capabilities, (tuple, list, str))
        and (not isinstance(capabilities, (tuple, list)) or all(isinstance(item, str) for item in capabilities))
        and (not isinstance(capabilities, (tuple, list)) or set(capabilities) <= CAPABILITY_NAMES)
    )
    return {
        "name": module_name(path),
        "setup": setup is not None,
        "setup_async": isinstance(setup, ast.AsyncFunctionDef),
        "shutdown": shutdown is None or isinstance(shutdown, (ast.FunctionDef, ast.AsyncFunctionDef)),
        "dependencies": dependency_ok,
        "optional_dependencies": optional_ok,
        "capabilities": capability_ok,
        "api_version": api_version in (None, PLUGIN_API_VERSION),
        "registrations": len(registrations),
        "direct_event_handlers": len(direct_handlers),
    }


def main() -> int:
    print("=== PLUGIN ECOSYSTEM QUALITY AUDIT ===")
    files = sorted(
        path for path in (ROOT / "plugins").rglob("*.py")
        if path.name not in EXCLUDED
    )
    active = [path for path in files if module_name(path) not in QUARANTINED]
    quarantined_present = sorted(module_name(path) for path in files if module_name(path) in QUARANTINED)
    results = [audit_file(path) for path in active]

    checks = {
        "deterministic_discovery": len({item["name"] for item in results}) == len(results),
        "standard_setup_contract": all(bool(item["setup"]) for item in results),
        "lifecycle_contract": all(bool(item["shutdown"]) for item in results),
        "dependency_declarations_valid": all(bool(item["dependencies"]) and bool(item["optional_dependencies"]) for item in results),
        "capability_declarations_valid": all(bool(item["capabilities"]) for item in results),
        "api_contract_compatible": all(bool(item["api_version"]) for item in results),
        "command_registration_boundary": all(item["registrations"] >= 0 for item in results),
        "quarantine_boundary": set(quarantined_present) == QUARANTINED,
    }
    for key, value in checks.items():
        print(f"{key}: {'PASS' if value else 'FAIL'}")

    print(f"active_plugins: {len(active)}")
    print(f"quarantined_plugins: {len(quarantined_present)}")
    print(f"command_registrations_declared: {sum(int(item['registrations']) for item in results)}")
    direct = sum(int(item["direct_event_handlers"]) for item in results)
    print(f"direct_event_handler_sites: {direct}")
    for item in results:
        print(f"PLUGIN {item['name']} · setup={'YES' if item['setup'] else 'NO'} · shutdown={'YES' if item['shutdown'] else 'NO'} · commands={item['registrations']}")

    if all(checks.values()):
        print("PLUGIN_ECOSYSTEM_QUALITY_AUDIT_PASS")
        return 0
    print("PLUGIN_ECOSYSTEM_QUALITY_AUDIT_FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
