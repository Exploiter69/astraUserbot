import asyncio
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from client import create_client
from config import config
from core import bootstrap, loader
from core.context import ApplicationContext, set_application_context
from core.registry import list_registrations

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)

LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "astra.log"


class SecretFilter(logging.Filter):
    """Prevent common credential-shaped values from entering Astra logs."""
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        message = re.sub(r"(?i)(api[_-]?hash|api[_-]?id|token|secret|password|authorization|session)[^\n:=]*[:=]\s*[^\n]+", r"\1=[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
file_handler.setFormatter(formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
file_handler.addFilter(SecretFilter())
console_handler.addFilter(SecretFilter())

root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
root_logger.handlers.clear()
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger("astra.main")


def _command_count() -> int:
    """Count concrete command names exposed by the live registry, including aliases."""
    total = 0
    prefix = re.escape(config.PREFIX)
    for registration in list_registrations():
        names: list[str] = []
        expression = registration.pattern
        if expression.startswith(f"^{prefix}"):
            expression = expression[len(f"^{prefix}"):]
            if expression.startswith("("):
                end = expression.find(")")
                group = expression[1:end] if end > 0 else ""
                if re.fullmatch(r"[A-Za-z0-9_:-]+(?:\|[A-Za-z0-9_:-]+)*", group):
                    names.extend(group.split("|"))
            else:
                match = re.match(r"[A-Za-z0-9_:-]+", expression)
                if match:
                    names.append(match.group(0))
        names.extend(str(alias).lstrip(config.PREFIX) for alias in registration.aliases)
        total += len(set(name.lower() for name in names if name))
    return total


async def _startup_hud(context: ApplicationContext, plugin_manager, client) -> str:
    """Build a live startup HUD from runtime state rather than a second config table."""
    records = plugin_manager.snapshot() if plugin_manager else []
    running = sum(item["state"] == "RUNNING" for item in records)
    services = len(context.services)
    jobs_ready = bool(getattr(context.get("jobs"), "_started", False))
    isolation = context.get("isolation").assess()
    ai = context.get("ai")
    database_ok = await context.get("storage").integrity_check()
    telegram = client.is_connected()
    return "\n".join([
        "ASTRA USERBOT",
        "─────────────────────────",
        "Runtime       READY",
        f"Telegram      {'CONNECTED' if telegram else 'DISCONNECTED'}",
        f"Database      {'PASS' if database_ok else 'FAIL'}",
        f"Services      {services}/{services}",
        f"Plugins       {running} RUNNING",
        f"Commands      {_command_count()}",
        f"Jobs          {'READY' if jobs_ready else 'STOPPED'}",
        f"Isolation     {str(isolation.backend).upper()}",
        f"AI Gateway    {str(ai.provider_name).upper()} READY",
        "─────────────────────────",
        "SYSTEM READY" if telegram and database_ok and services and running else "SYSTEM DEGRADED",
    ])


async def main():
    logger.info("Initializing Astra Userbot...")
    logger.info("Persistent log: %s", LOG_FILE)
    client = create_client()
    plugin_manager = None
    context: ApplicationContext | None = None
    shutdown_lock = asyncio.Lock()
    shutdown_complete = False

    async def graceful_shutdown() -> None:
        nonlocal shutdown_complete
        async with shutdown_lock:
            if shutdown_complete:
                return
            shutdown_started = asyncio.get_running_loop().time()
            logger.info("Initiating full runtime shutdown...")
            if plugin_manager is not None:
                stage_started = asyncio.get_running_loop().time()
                await plugin_manager.shutdown()
                logger.info("Plugin shutdown completed in %.3fs", asyncio.get_running_loop().time() - stage_started)
            if context is not None:
                stage_started = asyncio.get_running_loop().time()
                await context.close()
                logger.info("ApplicationContext shutdown completed in %.3fs", asyncio.get_running_loop().time() - stage_started)
            stage_started = asyncio.get_running_loop().time()
            await bootstrap.shutdown(client)
            logger.info("Bootstrap teardown completed in %.3fs", asyncio.get_running_loop().time() - stage_started)
            shutdown_complete = True
            logger.info("Full runtime shutdown completed in %.3fs", asyncio.get_running_loop().time() - shutdown_started)

    try:
        await client.start()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized")
        logger.info("Telethon client connected and authorized.")

        context = ApplicationContext(client, PROJECT_ROOT)
        set_application_context(context)
        client.application_context = context
        await context.start()
        logger.info("Shared runtime services initialized: %s", context.snapshot()["services"])

        plugin_manager = await loader.load_plugins(client)
        logger.info("\n%s", await _startup_hud(context, plugin_manager, client))

        loop = asyncio.get_running_loop()
        bootstrap.install_signal_handlers(loop, client, graceful_shutdown)

        logger.info("Startup complete. Running until disconnected.")
        await client.run_until_disconnected()
    finally:
        await graceful_shutdown()
        set_application_context(None)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
