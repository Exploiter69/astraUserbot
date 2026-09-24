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
    print("=== ASTRA PRODUCTION ACCEPTANCE GATE ===")
    print(f"python={PYTHON}")
    print(f"root={ROOT}")
    for index, command in enumerate(STEPS, 1):
        print(f"\n--- GATE {index}/{len(STEPS)} ---")
        print("$", " ".join(command))
        completed = subprocess.run(\n            command,\n            cwd=ROOT,\n            check=False,\n            text=True,\n            capture_output=True,\n        )\n        if completed.returncode != 0:\n            print(f"PRODUCTION_ACCEPTANCE_FAIL gate={index} rc={completed.returncode}")\n            if completed.stdout:\n                print("--- stdout ---")\n                print(completed.stdout.rstrip())\n            if completed.stderr:\n                print("--- stderr ---")\n                print(completed.stderr.rstrip())\n            return completed.returncode or 1\n        print(f"PASS gate={index}")\n    print("\nPRODUCTION_ACCEPTANCE_PASS")
    print("Manual systemd/Telegram acceptance remains required; this gate is non-destructive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
