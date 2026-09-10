import importlib
import logging
from pathlib import Path
from config import config

logger = logging.getLogger(__name__)

async def load_plugins(client):
    if config.SAFE_MODE:
        logger.warning("SAFE_MODE is active. Skipping plugin initialization.")
        return

    project_root = Path(__file__).resolve().parent.parent
    base_path = project_root / "plugins"
    if not base_path.exists():
        logger.warning(f"Plugin directory {base_path} not found.")
        return

    plugin_files = sorted(base_path.rglob("*.py"))

    loaded: list[str] = []
    failed: list[tuple[str, str]] = []

    for file_path in plugin_files:
        if file_path.name == "__init__.py":
            continue

        relative = file_path.relative_to(project_root).with_suffix("")
        module_path = ".".join(relative.parts)

        module = None
        try:
            module = importlib.import_module(module_path)
            if hasattr(module, "setup"):
                logger.info(f"Setting up plugin: {module_path}")
                await module.setup(client)
                loaded.append(module_path)
        except Exception as e:
            is_critical = bool(getattr(module, "critical", False)) if module is not None else False
            logger.error(f"Failed to load {module_path}: {e}", exc_info=True)
            failed.append((module_path, str(e)))
            if is_critical:
                logger.critical(f"Critical plugin {module_path} failed. Halting startup.")
                raise e

    logger.info(f"Plugin load complete: {len(loaded)} loaded, {len(failed)} failed.")
    if failed:
        logger.warning("Plugins that FAILED to load (their commands will NOT respond):")
        for name, err in failed:
            logger.warning(f"  - {name}: {err}")
