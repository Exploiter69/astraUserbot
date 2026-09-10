import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)
except ImportError:
    pass


def _required_int(name: str, *aliases: str) -> int:
    value = next((os.getenv(key) for key in (name, *aliases) if os.getenv(key)), None)
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return parsed


def _required_text(name: str, *aliases: str) -> str:
    value = next((os.getenv(key) for key in (name, *aliases) if os.getenv(key)), None)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


@dataclass(frozen=True)
class Config:
    API_ID: int = _required_int("ASTRA_API_ID", "API_ID")
    API_HASH: str = _required_text("ASTRA_API_HASH", "API_HASH")
    SESSION_NAME: str = os.environ.get("ASTRA_SESSION_NAME", os.environ.get("SESSION_NAME", "astra_session"))
    PREFIX: str = os.environ.get("ASTRA_PREFIX", os.environ.get("PREFIX", "."))
    OWNER_ID: int = _required_int("ASTRA_OWNER_ID", "OWNER_ID")
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
    RCLONE_REMOTE: str = os.environ.get("RCLONE_REMOTE", "teldrive-crypt:")
    LOG_LEVEL: str = os.environ.get("ASTRA_LOG_LEVEL", "INFO").upper()
    SAFE_MODE: bool = os.environ.get("ASTRA_SAFE_MODE", "0") == "1"


config = Config()
