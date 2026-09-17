"""Static Phase 9 media/investigation contract audit; never imports project plugins."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "media_service": ROOT / "core/services/media.py",
    "media_intel": ROOT / "core/services/media_intel.py",
    "cases": ROOT / "core/services/cases.py",
    "plugin": ROOT / "plugins/intelligence/media_cases.py",
}


def check(label: str, condition: bool) -> None:
    print(f"{label:<34} {'PASS' if condition else 'FAIL'}")
    if not condition:
        raise SystemExit(1)


def main() -> int:
    print("=== PHASE 9 MEDIA / INVESTIGATION AUDIT ===")
    for label, path in REQUIRED.items():
        check(label + " exists", path.is_file())
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        check(label + " parses", True)

    media = REQUIRED["media_intel"].read_text(encoding="utf-8")
    cases = REQUIRED["cases"].read_text(encoding="utf-8")
    plugin = REQUIRED["plugin"].read_text(encoding="utf-8")
    check("content addressing", "sha256" in media and "HASH" in media)
    check("perceptual matching", "PHASH_DISTANCE" in media and "_hamming" in media)
    check("isolated media execution", "run_isolated" in media)
    check("OCR boundary", "tesseract" in media and "MAX_TEXT" in media)
    check("audio/video extraction", "audio.wav" in media and "16000" in media)
    check("durable case schema", "CREATE TABLE IF NOT EXISTS cases" in cases)
    check("case timeline", "case_timeline" in cases)
    check("case report", "async def report" in cases)
    check("media command", "mediaintel" in plugin)
    check("case command", "case" in plugin)
    check("no shell=True", "shell=True" not in media and "shell=True" not in cases and "shell=True" not in plugin)
    check("no direct network client", "requests" not in media and "httpx" not in media)
    print("PHASE_9_STATIC_AUDIT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
