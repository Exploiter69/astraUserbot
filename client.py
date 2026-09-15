from pathlib import Path

from telethon import TelegramClient

from config import config


def create_client() -> TelegramClient:
    session_dir = Path(__file__).resolve().parent / "data"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / config.SESSION_NAME

    client = TelegramClient(
        str(session_path),
        config.API_ID,
        config.API_HASH,
        timeout=15,
        request_retries=5,
        connection_retries=10,
        retry_delay=2,
        auto_reconnect=True,
        flood_sleep_threshold=60,
        device_model="Astra Userbot",
        app_version="1.0",
    )

    # Telegram's persistent SQLite session is the authentication/state store.
    # Astra keeps its own durable entity/state projections, so Telethon's
    # optional entity persistence only adds high-frequency SQLite writes and can
    # contend with update/difference handling. Keep entities in Telethon's
    # in-memory cache and let the facade/state cache resolve them when needed.
    client.session.save_entities = False
    return client
