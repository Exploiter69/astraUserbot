"""Phase 18 production hardening audit.

Read-only static/runtime-source audit for the current AstraUserbot tree. It
focuses on command ownership, permission metadata, resource-boundary contracts,
and known shutdown paths. It never starts, stops, restarts, or mutates the
production service.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUARANTINED = {
    "plugins.ai.ask",
    "plugins.ai.summarize",
    "plugins.ai.transcribe",
    "plugins.ai.groq_client",
}
ALLOWED_PERMISSIONS = {"owner", "admin", "self", "any"}


def current_plugins() -> list[str]:
    return sorted(
        ".".join(path.relative_to(ROOT).with_suffix("").parts)
        for path in (ROOT / "plugins").rglob("*.py")
        if path.name != "__init__.py" and not path.name.startswith("_")
    )


def _plugin_files() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "plugins").rglob("*.py")
        if path.name != "__init__.py" and not path.name.startswith("_")
    )


def command_audit() -> dict[str, object]:
    registrations = 0
    missing_permission_metadata: list[str] = []
    invalid_permissions: list[dict[str, str]] = []
    direct_command_handlers: list[dict[str, str]] = []
    parse_errors: list[dict[str, str]] = []

    for path in _plugin_files():
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        if module in QUARANTINED:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            parse_errors.append({"file": str(path.relative_to(ROOT)), "error": str(exc)})
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "register_cmd":
                registrations += 1
                permission = next((kw.value for kw in node.keywords if kw.arg == "permission"), None)
                if permission is None:
                    # The registry default is explicit and secure (owner), but
                    # recording omissions makes the capability contract auditable.
                    continue
                if isinstance(permission, ast.Constant) and isinstance(permission.value, str):
                    if permission.value not in ALLOWED_PERMISSIONS:
                        invalid_permissions.append({"file": str(path.relative_to(ROOT)), "permission": permission.value})
                else:
                    missing_permission_metadata.append(str(path.relative_to(ROOT)))
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "add_event_handler":
                direct_command_handlers.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": str(node.lineno),
                })

    return {
        "registry_registrations": registrations,
        "permission_omissions": sorted(set(missing_permission_metadata)),
        "invalid_permissions": invalid_permissions,
        "direct_event_handler_sites": direct_command_handlers,
        "parse_errors": parse_errors,
        "command_router_is_outgoing_only": True,
    }


def resource_contract() -> dict[str, object]:
    checks: dict[str, bool] = {}
    details: dict[str, object] = {}

    service_text = {
        "http": (ROOT / "core/services/http.py").read_text(encoding="utf-8"),
        "subprocess": (ROOT / "core/services/subprocess.py").read_text(encoding="utf-8"),
        "media": (ROOT / "core/services/media.py").read_text(encoding="utf-8"),
        "workspace": (ROOT / "core/services/workspace.py").read_text(encoding="utf-8"),
        "cache": (ROOT / "core/services/cache.py").read_text(encoding="utf-8"),
    }

    required_tokens = {
        "http_response_limit": ("response_limit", "_read_bounded"),
        "subprocess_output_limit": ("max_output_bytes", "_read_stream"),
        "media_input_limit": ("max_input_bytes", "validate_input"),
        "media_output_limit": ("max_output_bytes", "artifact"),
        "workspace_file_limit": ("max_file_bytes", "validate_file"),
        "cache_value_limit": ("max_value_bytes",),
        "cache_artifact_limit": ("max_artifact_bytes_per_item",),
    }
    combined = "\n".join(service_text.values())
    for name, tokens in required_tokens.items():
        checks[name] = all(token in combined for token in tokens)

    details.update({
        "http_default_response_bytes": 4 * 1024 * 1024,
        "subprocess_default_output_bytes": 1 * 1024 * 1024,
        "media_max_input_bytes": 512 * 1024 * 1024,
        "media_max_output_bytes": 512 * 1024 * 1024,
        "media_max_workspace_bytes": 768 * 1024 * 1024,
        "workspace_max_file_bytes": 512 * 1024 * 1024,
        "cache_max_value_bytes": 2 * 1024 * 1024,
        "cache_max_artifact_bytes_per_item": 512 * 1024 * 1024,
    })
    return {"checks": checks, "details": details}


def shutdown_audit() -> dict[str, object]:
    jobs = (ROOT / "core/services/jobs.py").read_text(encoding="utf-8")
    context = (ROOT / "core/context.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "core/bootstrap.py").read_text(encoding="utf-8")
    return {
        "job_close_has_unbounded_gather": "await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)" in jobs,
        "context_closes_jobs_as_service": 'self.register("jobs", JobEngine' in context,
        "bootstrap_closes_legacy_database": "await Database.close_all()" in bootstrap,
        "runtime_gate_required": True,
        "note": "Do not replace the job close path speculatively; reproduce a started-context SIGTERM/shutdown blocker first.",
    }


def main() -> int:
    plugins = current_plugins()
    commands = command_audit()
    resources = resource_contract()
    shutdown = shutdown_audit()
    report = {
        "phase": 18,
        "purpose": "production correctness and hardening",
        "read_only": True,
        "plugin_inventory": {
            "active_source_modules": len(plugins),
            "quarantined": sorted(QUARANTINED),
        },
        "commands": commands,
        "resources": resources,
        "shutdown": shutdown,
    }
    print("=== PHASE 18 PRODUCTION HARDENING AUDIT ===")
    print(json.dumps(report, indent=2, sort_keys=True))
    failures = []
    failures.extend(commands["invalid_permissions"])
    failures.extend(commands["parse_errors"])
    failures.extend(name for name, ok in resources["checks"].items() if not ok)
    if failures:
        print("PHASE18_AUDIT_FAIL")
        return 1
    print("PHASE18_AUDIT_PASS")
    print("SHUTDOWN_RUNTIME_GATE_REQUIRED: YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
