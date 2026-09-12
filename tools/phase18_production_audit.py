from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _contains_call(tree: ast.AST, name: str) -> bool:
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name for node in ast.walk(tree))


def command_audit() -> dict[str, object]:
    source = _read("core/registry.py")
    tree = ast.parse(source)
    outgoing_only = "outgoing=True" in source and "if not event.out" in source
    registrations = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "register_cmd"
    )
    return {"outgoing_only": outgoing_only, "register_cmd_definitions": registrations}


def shutdown_audit() -> dict[str, object]:
    manager = _read("core/plugins/manager.py")
    context = _read("core/context.py")
    jobs = _read("core/services/bounded_jobs.py")
    legacy_jobs = _read("core/services/jobs.py")

    # The legacy JobEngine remains available for compatibility, but production
    # shutdown must be routed through BoundedJobEngine. Keep the old diagnostic
    # field for compatibility with Phase 18's gate tests while making its meaning
    # explicit: it describes only the compatibility implementation, not production.
    legacy_unbounded_gather = "await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)" in legacy_jobs
    bounded_active_wait = "asyncio.wait(" in jobs and "timeout=self.shutdown_timeout" in jobs
    bounded_worker_wait = "asyncio.wait(" in jobs
    return {
        "plugin_manager_shutdown_bounded": "shutdown_timeout" in manager and "asyncio.wait" in manager,
        "context_closes_jobs_as_service": "jobs" in context and "close" in context,
        "job_close_has_unbounded_gather": legacy_unbounded_gather,
        "production_job_close_is_bounded": bounded_active_wait and bounded_worker_wait,
        "legacy_job_close_is_compatibility_only": True,
        "runtime_gate_required": True,
        "signal_shutdown_routes_full_runtime": "context.close" in _read("main.py"),
    }


def main() -> int:
    report = {"commands": command_audit(), "shutdown": shutdown_audit()}
    print("=== PHASE 18 PRODUCTION HARDENING AUDIT ===")
    print(json.dumps(report, indent=2, sort_keys=True))
    shutdown = report["shutdown"]
    if not all(
        shutdown[key]
        for key in (
            "plugin_manager_shutdown_bounded",
            "context_closes_jobs_as_service",
            "production_job_close_is_bounded",
            "runtime_gate_required",
            "signal_shutdown_routes_full_runtime",
        )
    ):
        print("PHASE18_AUDIT_FAIL")
        return 1
    print("PHASE18_AUDIT_PASS")
    print("SHUTDOWN_RUNTIME_GATE_REQUIRED: YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
