import asyncio
import re
import sys
import tempfile
from pathlib import Path

from core.registry import register_cmd
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}eval(?:\s+(.*))?$"
_MAX_OUTPUT = 6000
_EVAL_TIMEOUT = 30
_MAX_CODE = 12000


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_eval,
        category="system",
        description="Evaluate standalone Python code in a child process so blocking code cannot freeze the bot event loop.",
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

    with tempfile.TemporaryDirectory(prefix="astra-eval-") as tmp:
        root = Path(tmp)
        script = root / "eval.py"
        stdout = root / "stdout.txt"
        stderr = root / "stderr.txt"
        script.write_text(_script(code), encoding="utf-8")
        out_handle = stdout.open("wb")
        err_handle = stderr.open("wb")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(script),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=out_handle,
                stderr=err_handle,
                cwd=tmp,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=_EVAL_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                rows = [
                    "Execution failed:",
                    "---",
                    f"Evaluation timed out after {_EVAL_TIMEOUT} seconds.",
                ]
            else:
                out_text = stdout.read_text(encoding="utf-8", errors="replace")
                err_text = stderr.read_text(encoding="utf-8", errors="replace")
                if proc.returncode == 0:
                    rows = ["Code executed successfully."]
                    if out_text.strip():
                        rows.extend(["---", *_trim(out_text)])
                    else:
                        rows.append("No stdout output.")
                else:
                    error_lines = _trim(err_text)[:20]
                    rows = ["Execution failed:", "---", *error_lines]
                    if not error_lines:
                        rows.append(f"Child process exited with code {proc.returncode}.")
        finally:
            out_handle.close()
            err_handle.close()

    await event.edit(render("EVAL", rows, footer="system | eval | child-process"))
