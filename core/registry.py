import time
import logging
from typing import Callable, Any, Optional, List, Dict
from telethon import events
from core.errors import CommandError
from helpers.hud import render
from config import config

logger = logging.getLogger("astra.registry")

# Global registry for introspection by plugins/system/help.py
COMMANDS: Dict[str, Dict[str, Any]] = {}

def register_cmd(
    client: Any, 
    pattern: str, 
    handler: Callable, 
    category: str = "system", 
    description: str = "No description provided.", 
    aliases: Optional[List[str]] = None
):
    COMMANDS[pattern] = {
        "handler": handler.__name__,
        "category": category,
        "description": description,
        "aliases": aliases or []
    }
    
    async def wrapper(event):
        if not event.out:
            return
            
        start_time = time.perf_counter()
        try:
            await handler(event)
        except CommandError as e:
            elapsed = time.perf_counter() - start_time
            await event.edit(render(
                title="ERROR",
                rows=[e.message],
                footer=f"{elapsed:.2f}s | {category}"
            ))
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            logger.error(f"Unhandled exception in {handler.__name__}: {e}", exc_info=True)
            await event.edit(render(
                title="CRITICAL FAULT",
                rows=[f"Exception: {type(e).__name__}", f"Details: {str(e)}"],
                footer=f"{elapsed:.2f}s | {category}"
            ))
            
    client.add_event_handler(wrapper, events.NewMessage(outgoing=True, pattern=pattern))
    logger.debug(f"Registered command {pattern} in category [{category}]")
