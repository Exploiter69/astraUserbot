"""Formal plugin metadata contract and legacy compatibility normalization.

Plugins remain ordinary Python modules. This module makes their metadata
machine-readable without forcing a framework migration: explicit metadata is
preferred, while legacy setup-only modules receive deterministic defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any

PLUGIN_API_VERSION = 1


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    name: str
    version: str
    api_version: int
    description: str
    dependencies: tuple[str, ...]
    optional_dependencies: tuple[str, ...]
    capabilities: tuple[str, ...]
    critical: bool


def _tuple_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    try:
        values = tuple(str(item).strip() for item in value)
    except TypeError as exc:
        raise ValueError("metadata collection must be iterable") from exc
    if any(not item or len(item) > 128 for item in values):
        raise ValueError("metadata collection contains an invalid item")
    if len(values) != len(set(values)):
        raise ValueError("metadata collection contains duplicates")
    return values


def metadata_for(module: ModuleType, module_name: str | None = None) -> PluginMetadata:
    """Normalize explicit or legacy module metadata into one immutable record."""
    name = str(getattr(module, "plugin_name", module_name or module.__name__)).strip()
    if not name or len(name) > 256:
        raise ValueError("plugin name must be 1..256 characters")
    version = str(getattr(module, "plugin_version", "legacy")).strip()
    if not version or len(version) > 64:
        raise ValueError("plugin version must be 1..64 characters")
    try:
        api_version = int(getattr(module, "plugin_api_version", PLUGIN_API_VERSION))
    except (TypeError, ValueError) as exc:
        raise ValueError("plugin_api_version must be an integer") from exc
    if api_version != PLUGIN_API_VERSION:
        raise ValueError(f"unsupported plugin api version: {api_version}")
    description = str(getattr(module, "plugin_description", getattr(module, "description", ""))).strip()
    if len(description) > 512:
        raise ValueError("plugin description exceeds 512 characters")
    dependencies = _tuple_strings(getattr(module, "dependencies", ()))
    optional = _tuple_strings(getattr(module, "optional_dependencies", ()))
    capabilities = _tuple_strings(getattr(module, "capabilities", ()))
    critical = bool(getattr(module, "critical", False))
    return PluginMetadata(
        name=name,
        version=version,
        api_version=api_version,
        description=description,
        dependencies=dependencies,
        optional_dependencies=optional,
        capabilities=capabilities,
        critical=critical,
    )
