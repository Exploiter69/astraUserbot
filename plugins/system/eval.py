import re
import sys
import io
import traceback
from telethon import events
from core.registry import register_cmd
from helpers.hud import render
from config import config

# DANGEROUS: Owner-gated by core.registry inherently.
PATTERN = rf"^{re.escape(config.PREFIX)}eval(?:\s+(.*))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_eval,
        category="system",
        description="Evaluate raw Python expressions dynamically."
    )

async def handle_eval(event):
    code = event.pattern_match.group(1)
    if not code:
        await event.edit(render(title="EVAL", rows=["Error: No code provided."], footer="system | eval"))
        return

    # Redirect stdout to capture print() statements within the eval
    old_stdout = sys.stdout
    redirected_output = sys.stdout = io.StringIO()
    
    try:
        # Wrap the expression in an async function to allow 'await' inside .eval
        wrapped_code = f"async def __ex(event, client):\n"
        for line in code.split("\n"):
            wrapped_code += f"    {line}\n"
            
        exec_locals = {}
        exec(wrapped_code, globals(), exec_locals)
        func = exec_locals["__ex"]
        
        await func(event, event.client)
        
        stdout_result = redirected_output.getvalue()
        rows = ["Code executed successfully."]
        if stdout_result:
            rows.append("---")
            rows.extend(stdout_result.strip().split("\n"))
            
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        rows = ["Execution Failed:", "---"]
        # Only take the last few lines of the traceback to avoid exceeding max message length
        rows.extend([line.strip() for line in tb_lines[-4:]])
    finally:
        sys.stdout = old_stdout

    await event.edit(render(
        title="EVAL",
        rows=rows,
        footer="system | eval"
    ))
