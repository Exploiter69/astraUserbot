"""Read-only plugin registry and compatibility manifest generator.

The registry inspects plugin source with AST and never imports third-party code.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins"
API_VERSION = 1
MAX_PLUGINS = 512
MAX_FIELD = 256


def _literal(tree: ast.Module, name: str, default):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return default
    return default


def _strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item)[:MAX_FIELD] for item in value]
    return []


def build_registry() -> list[dict]:
    rows = []
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        if len(rows) >= MAX_PLUGINS:
            break
        relative = path.relative_to(ROOT).with_suffix("")
        module = ".".join(relative.parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rows.append({
            "module": module,
            "name": str(_literal(tree, "plugin_name", module))[:MAX_FIELD],
            "version": str(_literal(tree, "plugin_version", "legacy"))[:64],
            "api_version": int(_literal(tree, "plugin_api_version", API_VERSION)),
            "description": str(_literal(tree, "plugin_description", ""))[:512],
            "dependencies": _strings(_literal(tree, "dependencies", [])),
            "optional_dependencies": _strings(_literal(tree, "optional_dependencies", [])),
            "capabilities": _strings(_literal(tree, "capabilities", [])),
            "critical": bool(_literal(tree, "critical", False)),
        })
    return rows


def validate_registry(rows: list[dict]) -> list[str]:
    errors = []
    names = set()
    for row in rows:
        if row["name"] in names:
            errors.append(f"duplicate plugin name: {row['name']}")
        names.add(row["name"])
        if row["api_version"] != API_VERSION:
            errors.append(f"{row['module']}: incompatible API {row['api_version']}")
        if not row["module"].startswith("plugins."):
            errors.append(f"{row['module']}: module outside plugin namespace")
    modules = {row["module"] for row in rows}
    for row in rows:
        for dep in row["dependencies"]:
            if dep not in modules:
                errors.append(f"{row['module']}: unknown dependency {dep}")
    return errors


def main() -> int:
    rows = build_registry()
    errors = validate_registry(rows)
    payload = {
        "api_version": API_VERSION,
        "plugin_count": len(rows),
        "compatible": not errors,
        "errors": errors,
        "plugins": rows,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
