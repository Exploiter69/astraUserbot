"""Read-only behavioral contract audit for active AstraUserbot plugins."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
SKIP_PARTS = {"__pycache__", ".git", ".venv", "venv", "env", ".pytest_cache"}
ALLOWED_DIRECT_EVENT_PLUGINS = {
    "plugins/security/account_archiver.py",
    "plugins/security/acl.py",
    "plugins/security/logger.py",
    "plugins/security/pmguard.py",
    "plugins/system/afk.py",
    "plugins/productivity.py",
}
QUARANTINED = {
    "plugins.ai.ask",
    "plugins.ai.groq_client",
    "plugins.ai.summarize",
    "plugins.ai.transcribe",
}


def py_files() -> list[Path]:
    return sorted(p for p in PLUGINS.rglob("*.py") if not any(part in SKIP_PARTS for part in p.parts))


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def command_handlers(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "register_cmd" for d in node.decorator_list):
            yield node


def has_benign_broad_except(handler: ast.ExceptHandler) -> bool:
    body = handler.body
    text = ast.unparse(ast.Module(body=body, type_ignores=[])).lower()
    return any(token in text for token in ("raise", "logger.", "logging.", "return false", "return none"))


def main() -> int:
    findings: list[str] = []
    metrics = {
        "source_modules": 0,
        "active_source_modules": 0,
        "command_handlers": 0,
        "parse_errors": 0,
        "direct_incoming_event_sites": 0,
        "unexpected_direct_event_sites": 0,
        "silent_broad_except_reviews": 0,
        "shell_api_calls": 0,
        "shell_true_calls": 0,
        "raw_sql_interpolation_reviews": 0,
        "unguarded_artifact_index_reviews": 0,
        "direct_media_download_reviews": 0,
    }

    for path in py_files():
        metrics["source_modules"] += 1
        rel = path.relative_to(ROOT)
        active = module_name(path) not in QUARANTINED
        if active:
            metrics["active_source_modules"] += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            metrics["parse_errors"] += 1
            if active:
                findings.append(f"PARSE_ERROR {rel}:{exc.lineno}")
            continue
        if not active:
            continue

        for fn in command_handlers(tree):
            metrics["command_handlers"] += 1
            for node in ast.walk(fn):
                if isinstance(node, ast.ExceptHandler) and node.type is None and not has_benign_broad_except(node):
                    metrics["silent_broad_except_reviews"] += 1
                    findings.append(f"SILENT_BROAD_EXCEPT_REVIEW {rel}:{node.lineno} {fn.name}")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "NewMessage":
                incoming = any(
                    kw.arg == "incoming"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in node.keywords
                )
                if incoming:
                    metrics["direct_incoming_event_sites"] += 1
                    if str(rel) not in ALLOWED_DIRECT_EVENT_PLUGINS:
                        metrics["unexpected_direct_event_sites"] += 1
                        findings.append(f"UNEXPECTED_DIRECT_EVENT_REVIEW {rel}:{node.lineno}")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "create_subprocess_shell":
                metrics["shell_api_calls"] += 1
                findings.append(f"SHELL_API_REVIEW {rel}:{node.lineno}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"run", "run_sync", "create_subprocess_exec"} and any(
                kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True for kw in node.keywords
            ):
                metrics["shell_true_calls"] += 1
                findings.append(f"SHELL_TRUE {rel}:{node.lineno}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "executemany", "executescript"} and node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                metrics["raw_sql_interpolation_reviews"] += 1
                findings.append(f"SQL_INTERPOLATION_REVIEW {rel}:{node.lineno}")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "download_media":
                metrics["direct_media_download_reviews"] += 1
                if any(part in str(rel) for part in ("plugins/media/", "plugins/media_ops/", "plugins/security/ephemeral.py", "plugins/ai_gateway/transcribe.py")):
                    findings.append(f"DIRECT_MEDIA_DOWNLOAD_REVIEW {rel}:{node.lineno}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == 0 and isinstance(node.value, ast.Name) and node.value.id in {"artifacts", "files", "results"}:
                metrics["unguarded_artifact_index_reviews"] += 1
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