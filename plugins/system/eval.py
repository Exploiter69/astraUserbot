import re
import tempfile
from pathlib import Path

from config import config
from core.context import get_application_context
from core.registry import register_cmd
from core.services.isolation import IsolationService
from helpers.hud import render

PATTERN = rf"^{re.escape(config.PREFIX)}eval(?:\s+(.*))?$"
_MAX_OUTPUT = 6000
_MAX_CODE = 12000
_EVAL_TIMEOUT = 30
_EVAL_MEMORY = 256 * 1024 * 1024
_EVAL_FILE_SIZE = 8 * 1024 * 1024
_EVAL_PROCESSES = 16


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_eval,
        category="system",
        description="Evaluate standalone Python code in an isolated child process with filesystem and network boundaries.",
    )


def _script(code: str) -> str:
    lines = code.splitlines() or [code]
    body = "\n".join(f"    {line}" for line in lines)
    return (
        "import asyncio\n"
        "async def __astra_eval__():\n"
        f"{body}\n"
        "asyncio.run(__astra_eval__())\n"
    )


def _trim(text: str) -> list[str]:
    text = text.replace("\x00", "")
    if len(text) > _MAX_OUTPUT:
        text = text[:_MAX_OUTPUT] + "\n[output truncated]"
    return text.strip().splitlines() if text.strip() else []


async def handle_eval(event):
    code = (event.pattern_match.group(1) or "").strip()
    if not code:
        await event.edit(render("EVAL", ["Error: No code provided."], footer="system | eval"))
        return
    if len(code) > _MAX_CODE:
        await event.edit(
            render(
                "EVAL",
                [f"Error: Code exceeds {_MAX_CODE} characters."],
                footer="system | eval",
            )
        )
        return

    context = get_application_context()
    isolation = context.get("isolation") if context is not None else None
    owned_isolation = False
    if isolation is None:
        isolation = IsolationService()
        await isolation.start()
        owned_isolation = True

    try:
        with tempfile.TemporaryDirectory(prefix="astra-eval-") as tmp:
            root = Path(tmp)
            script = root / "eval.py"
            script.write_text(_script(code), encoding="utf-8")
            try:
                result = await isolation.run(
                    ["python3", "-I", "/workspace/eval.py"],
                    workspace=root,
                    timeout=_EVAL_TIMEOUT + 2,
                    max_output_bytes=_MAX_OUTPUT + 1024,
                    memory_bytes=_EVAL_MEMORY,
                    file_bytes=_EVAL_FILE_SIZE,
                    processes=_EVAL_PROCESSES,
                )
            except Exception as exc:
                message = str(exc).strip() or "isolated execution failed"
                await event.edit(render("EVAL", ["Execution failed:", "---", *_trim(message)], footer="system | eval"))
                return

            if result.returncode == 0:
                rows = ["Code executed successfully."]
                if result.stdout.strip():
                    rows.extend(["---", *_trim(result.stdout)])
                else:
                    rows.append("No stdout output.")
            else:
                error_lines = _trim(result.stderr)[:20]
                rows = ["Execution failed:", "---", *error_lines]
                if not error_lines:
                    rows.append(f"Child process exited with code {result.returncode}.")

        await event.edit(render("EVAL", rows, footer="system | eval | isolated-child"))
    finally:
        if owned_isolation:
            await isolation.close()
