"""Read-only behavioral contract audit for active AstraUserbot plugins."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
SKIP_PARTS = {"__pycache__", ".git", ".venv", "venv", "env", ".pytest_cache"}


def py_files() -> list[Path]:
    return sorted(p for p in PLUGINS.rglob("*.py") if not any(part in SKIP_PARTS for part in p.parts))


def command_handlers(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Name)
            and d.func.id in {"register_cmd", "command"}
            for d in node.decorator_list
        ):
            yield node


def calls(tree: ast.AST, names: set[str]):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (isinstance(node.func, ast.Name) and node.func.id in names) or (
            isinstance(node.func, ast.Attribute) and node.func.attr in names
        ):
            yield node


def main() -> int:
    findings: list[str] = []
    metrics = {
        "source_modules": 0,
        "command_handlers": 0,
        "parse_errors": 0,
        "broad_except_handlers": 0,
        "shell_true_calls": 0,
        "sql_interpolation_reviews": 0,
        "artifact_index_reviews": 0,
    }

    for path in py_files():
        metrics["source_modules"] += 1
        rel = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            metrics["parse_errors"] += 1
            findings.append(f"PARSE_ERROR {rel}:{exc.lineno}")
            continue

        for fn in command_handlers(tree):
            metrics["command_handlers"] += 1
            for node in ast.walk(fn):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    metrics["broad_except_handlers"] += 1
                    findings.append(f"BROAD_EXCEPT {rel}:{node.lineno} {fn.name}")

        for node in calls(tree, {"create_subprocess_shell"}):
            metrics["shell_true_calls"] += 1
            findings.append(f"SHELL_API_REVIEW {rel}:{node.lineno}")
        for node in calls(tree, {"run", "run_sync", "create_subprocess_exec"}):
            if any(
                kw.arg == "shell"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            ):
                metrics["shell_true_calls"] += 1
                findings.append(f"SHELL_TRUE {rel}:{node.lineno}")

        for node in calls(tree, {"execute", "executemany", "executescript"}):
            if node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                metrics["sql_interpolation_reviews"] += 1
                findings.append(f"SQL_INTERPOLATION_REVIEW {rel}:{node.lineno}")

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == 0
                and isinstance(node.value, ast.Name)
                and node.value.id in {"artifacts", "files", "results"}
            ):
                metrics["artifact_index_reviews"] += 1
                findings.append(f"ARTIFACT_INDEX_REVIEW {rel}:{node.lineno}")

    print("=== PLUGIN / COMMAND BEHAVIOR AUDIT ===")
    for key, value in metrics.items():
        print(f"{key}: {value}")
    if findings:
        print("FINDINGS:")
        for finding in findings:
            print(f"- {finding}")
        print("PLUGIN_BEHAVIOR_AUDIT_REVIEW_REQUIRED")
        return 1
    print("PLUGIN_BEHAVIOR_AUDIT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
