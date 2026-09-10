import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from client import create_client
from config import config
from core import bootstrap, loader
from helpers.net import close_session

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)

LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "astra.log"


class SecretFilter(logging.Filter):
    """Prevent common credential-shaped values from entering Astra logs."""
    def filter(self, record: logging.LogRecord) -> bool:
        import re
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


async def main():
    logger.info("Initializing Astra Userbot...")
    logger.info("Persistent log: %s", LOG_FILE)
    client = create_client()

    try:
        await client.start()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized")
        logger.info("Telethon client connected and authorized.")

        loop = asyncio.get_running_loop()
        bootstrap.install_signal_handlers(loop, client)

        await loader.load_plugins(client)

        logger.info("Startup complete. Running until disconnected.")
        await client.run_until_disconnected()
    finally:
        await bootstrap.shutdown(client)
        await close_session()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
