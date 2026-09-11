import logging
from pathlib import Path
from typing import Any

from config import config
from core.plugins.manager import PluginManager

logger = logging.getLogger(__name__)


# Kept as the public compatibility entry point used by the existing bootstrap.
async def load_plugins(client: Any) -> PluginManager | None:
    if config.SAFE_MODE:
        logger.warning("SAFE_MODE is active. Skipping plugin initialization.")
        return None

    project_root = Path(__file__).resolve().parent.parent
    manager = PluginManager(client, project_root / "plugins")
    # The registry uses this optional reference to attribute registrations to
    # the lifecycle manager without changing the legacy register_cmd signature.
    client.plugin_manager = manager
    await manager.load_all()
    return manager
