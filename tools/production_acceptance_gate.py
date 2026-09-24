"""Run the non-destructive local production acceptance contract."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

STEPS = [
    [PYTHON, "tools/post_phase10_maturity_audit.py"],
    [PYTHON, "-m", "ruff", "check", "."],
    [PYTHON, "-m", "ruff", "format", "--check", "."],
    [
        PYTHON,
        "-m",
        "pytest",
        "-q",
        "tests/test_post_phase10_maturity.py",
        "tests/test_phase10_15_gate.py",
        "tests/test_runtime_services.py",
        "tests/test_phase16_gate.py",
    ],
    [PYTHON, "-m", "pytest", "-q"],
    [PYTHON, "-m", "compileall", "-q", "core", "plugins", "tools"],
    [PYTHON, "tools/plugin_behavior_audit.py"],
    [PYTHON, "tools/plugin_ecosystem_audit.py"],
    [PYTHON, "tools/media_pipeline_audit.py"],
    [PYTHON, "tools/isolation_security_audit.py"],
    [PYTHON, "tools/storage_hardening_audit.py"],
    [PYTHON, "tools/job_hardening_audit.py"],
    [PYTHON, "tools/phase18_production_audit.py"],
    [PYTHON, "tools/phase18_shutdown_probe.py"],
]


def main() -> int:
    print("=== ASTRA PRODUCTION ACCEPTANCE ===")
    for index, command in enumerate(STEPS, 1):
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            print(f"FAIL gate={index}/{len(STEPS)} rc={completed.returncode}")
            output = (completed.stdout or "") + (completed.stderr or "")
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            if command[2:4] == ["ruff", "check"]:
                findings = [line for line in lines if line.startswith(("I", "F", "E", "W", "UP", "SIM", "BLE", "S", "RUF", "TRY", "ASYNC", "G", "C", "RET", "FURB"))]
                print(f"ruff findings: {len(findings)}")
                for line in findings[:5]:
                    print(f"  {line}")
                if len(findings) > 5:
                    print(f"  ... {len(findings) - 5} more (run ruff check . for full details)")
            else:
                for line in lines[-8:]:
                    print(f"  {line}")
            return completed.returncode or 1
        print(f"PASS gate={index}/{len(STEPS)}")
    print("PRODUCTION_ACCEPTANCE_PASS")
    print("Manual systemd/Telegram acceptance remains required.")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
