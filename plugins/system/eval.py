import asyncio
import io
import re
from contextlib import redirect_stdout

from core.registry import register_cmd
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}eval(?:\s+(.*))?$"
_EVAL_LOCK = asyncio.Lock()
_MAX_OUTPUT = 6000
_EVAL_TIMEOUT = 30


async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_eval,
        category="system",
        description="Evaluate raw Python expressions dynamically.",
    )


def _build_function(code: str):
    wrapped_code = "async def __ex(event, client):\n"
    for line in code.split("\n"):
        wrapped_code += f"    {line}\n"
    namespace = {"__builtins__": __builtins__, "asyncio": asyncio}
    exec_locals = {}
    exec(wrapped_code, namespace, exec_locals)
    return exec_locals["__ex"]


async def handle_eval(event):
    code = event.pattern_match.group(1)
    if not code:
        await event.edit(render("EVAL", ["Error: No code provided."], footer="system | eval"))
        return

    # redirect_stdout is process-global, so concurrent evaluations must be serialized.
    async with _EVAL_LOCK:
        output = io.StringIO()
        rows = []
        try:
            func = _build_function(code)
            with redirect_stdout(output):
                await asyncio.wait_for(func(event, event.client), timeout=_EVAL_TIMEOUT)
            stdout_result = output.getvalue()
            if len(stdout_result) > _MAX_OUTPUT:
                stdout_result = stdout_result[:_MAX_OUTPUT] + "\n[output truncated]"
            rows = ["Code executed successfully."]
            if stdout_result:
                rows.extend(["---", *stdout_result.strip().splitlines()])
        except asyncio.TimeoutError:
            rows = ["Execution failed:", "---", "Evaluation timed out after 30 seconds."]
        except Exception as exc:
            error_name = type(exc).__name__ if type(exc).__name__.isalnum() else "Error"
            rows = ["Execution failed:", "---", f"{error_name}: execution error"]
        finally:
            output.close()

    await event.edit(render("EVAL", rows, footer="system | eval"))
