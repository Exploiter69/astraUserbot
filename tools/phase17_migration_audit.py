"""Phase 17 production migration-readiness audit.

Read-only against the runtime/environment. It does not stop, start, restart,
modify, or migrate the running bot.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "64538b1"

EXPECTED = [
    "main.py",
    "client.py",
    "config.py",
    "requirements.txt",
    "astra.service",
    ".env.example",
    ".gitignore",
    "core/context.py",
    "core/plugins/manager.py",
    "core/services",
    "tools/astra_platform.py",
    "tools/phase16_audit.py",
    "tests/test_phase16_gate.py",
    "DISASTER_RECOVERY.md",
    "PRODUCTION_BOUNDARY.md",
]

LEGACY_IMPORTS = {
    "requests",
    "httpx",
    "urllib.request",
    "helpers.shell",
    "helpers.net",
}

BASELINE = "64538b1"

QUARANTINED = {
    "plugins.ai.ask",
    "plugins.ai.summarize",
    "plugins.ai.transcribe",
    "plugins.ai.groq_client",
}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip()


def baseline_plugins() -> set[str]:
    output = git("ls-tree", "-r", "--name-only", BASELINE, "--", "plugins")
    return {
        line
        for line in output.splitlines()
        if line.endswith(".py")
        and not line.endswith("/__init__.py")
        and "/_" not in line
    }


def current_plugins() -> set[str]:
    return {
        str(path.relative_to(ROOT))
        for path in (ROOT / "plugins").rglob("*.py")
        if path.name != "__init__.py"
        and not path.name.startswith("_")
    }


def plugin_import_violations() -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []

    for path in sorted((ROOT / "plugins").rglob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue

        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        if module in QUARANTINED:
            continue

        try:
            tree = ast.parse(path.read_text())
        except Exception as exc:
            violations.append(
                {"file": str(path.relative_to(ROOT)), "reason": f"parse error: {exc}"}
            )
            continue

        for node in ast.walk(tree):
            imported = None

            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]

            if not imported:
                continue

            for name in imported:
                if name in LEGACY_IMPORTS or any(
                    name.startswith(prefix + ".") for prefix in LEGACY_IMPORTS
                ):
                    violations.append(
                        {
                            "file": str(path.relative_to(ROOT)),
                            "reason": f"forbidden legacy import: {name}",
                        }
                    )

    return violations


def runtime_processes() -> list[str]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,etime=,cmd="],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    rows = []
    for line in result.stdout.splitlines():
        if "AstraUserbot" in line or "astra.py" in line or "main.py" in line:
            if "phase17_migration_audit.py" not in line:
                rows.append(line.strip())
    return rows


def systemd_state() -> dict[str, str | None]:
    unit = ROOT / "astra.service"
    state: dict[str, str | None] = {
        "unit_file": str(unit) if unit.exists() else None,
        "systemctl_user": None,
        "systemctl_system": None,
    }

    for scope, command in (
        ("systemctl_user", ["systemctl", "--user", "is-active", "astra.service"]),
        ("systemctl_system", ["systemctl", "is-active", "astra.service"]),
    ):
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        value = result.stdout.strip() or result.stderr.strip()
        state[scope] = value or None

    return state


def check_expected_files() -> dict[str, bool]:
    return {item: (ROOT / item).exists() for item in EXPECTED}


def test_tools() -> dict[str, bool]:
    return {
        "python": shutil.which("python") is not None,
        "git": shutil.which("git") is not None,
        "systemctl": shutil.which("systemctl") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "rclone": shutil.which("rclone") is not None,
        "aria2c": shutil.which("aria2c") is not None,
    }


def main() -> int:
    baseline = baseline_plugins()
    current = current_plugins()
    missing = sorted(baseline - current)
    added = sorted(current - baseline)
    violations = plugin_import_violations()

    expected = check_expected_files()
    missing_expected = [name for name, ok in expected.items() if not ok]

    report = {
        "phase": 17,
        "purpose": "production migration readiness",
        "read_only": True,
        "baseline_commit": BASELINE,
        "current_commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "working_tree": git("status", "--short"),
        "plugin_inventory": {
            "baseline_python_modules": len(baseline),
            "current_python_modules": len(current),
            "missing_from_current": missing,
            "new_since_baseline": added,
            "quarantined": sorted(QUARANTINED),
        },
        "boundary_violations": violations,
        "expected_files_missing": missing_expected,
        "system_tools": test_tools(),
        "systemd": systemd_state(),
        "runtime_processes": runtime_processes(),
        "cutover_state": {
            "platform_verified_through_phase_16": True,
            "migration_audit_pass": not missing_expected and not violations,
            "live_cutover_authorized": False,
        },
    }

    print("=== PHASE 17 MIGRATION READINESS AUDIT ===")
    print(json.dumps(report, indent=2, sort_keys=True))

    output = ROOT / "data" / "logs" / "phase17_migration_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"\nREPORT_WRITTEN: {output.relative_to(ROOT)}")

    if missing_expected:
        print("PHASE17_AUDIT_FAIL: required project files are missing")
        return 1

    if violations:
        print("PHASE17_AUDIT_FAIL: active plugin boundary violations detected")
        return 1

    print("PHASE17_AUDIT_PASS")
    print("CUTOVER_AUTHORIZED: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
