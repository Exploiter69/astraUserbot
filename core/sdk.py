"""Implementation of the metadata adapter used by the public Astra SDK.

New plugins should import this API through :mod:`astra.sdk`. This module
adapts to the canonical runtime contract in :mod:`core.plugins.contract`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.plugins.capabilities import validate_capabilities
from core.plugins.contract import PLUGIN_API_VERSION, PluginMetadata as RuntimePluginMetadata

SDK_API_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    """Validated SDK metadata normalized to the runtime's canonical schema."""
    name: str
    version: str = "legacy"
    api_version: int = PLUGIN_API_VERSION
    description: str = ""
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    critical: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name.strip()) > 256:
            raise ValueError("plugin name must be 1..256 characters")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.version, str) or not self.version.strip() or len(self.version.strip()) > 64:
            raise ValueError("plugin version must be 1..64 characters")
        object.__setattr__(self, "version", self.version.strip())
        version: Any = self.api_version
        if isinstance(version, str):
            if version != SDK_API_VERSION:
                raise ValueError(f"unsupported plugin API version: {version}")
            version = PLUGIN_API_VERSION
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("api_version must be an integer or supported SDK version string")
        if version != PLUGIN_API_VERSION:
            raise ValueError(f"unsupported plugin api version: {version}")
        object.__setattr__(self, "api_version", version)
        if not isinstance(self.description, str) or len(self.description.strip()) > 512:
            raise ValueError("plugin description must be at most 512 characters")
        object.__setattr__(self, "description", self.description.strip())
        for field_name in ("dependencies", "optional_dependencies"):
            value = getattr(self, field_name)
            if isinstance(value, str) or not isinstance(value, (tuple, list)):
                raise ValueError(f"{field_name} must be a sequence of unique strings")
            normalized = tuple(item.strip() if isinstance(item, str) else item for item in value)
            if any(not isinstance(item, str) or not item or len(item) > 128 for item in normalized):
                raise ValueError(f"{field_name} contains an invalid item")
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{field_name} contains duplicates")
            object.__setattr__(self, field_name, normalized)
        object.__setattr__(self, "capabilities", validate_capabilities(self.capabilities))
        if not isinstance(self.critical, bool):
            raise ValueError("critical must be a boolean")

    def to_runtime_contract(self) -> RuntimePluginMetadata:
        return RuntimePluginMetadata(
            name=self.name, version=self.version, api_version=self.api_version,
            description=self.description, dependencies=self.dependencies,
            optional_dependencies=self.optional_dependencies, capabilities=self.capabilities,
            critical=self.critical,
        )

    def to_module_metadata(self) -> dict[str, Any]:
        """Map every accepted field to a runtime-consumed module attribute."""
        return {
            "plugin_name": self.name, "plugin_version": self.version,
            "plugin_api_version": self.api_version, "plugin_description": self.description,
            "dependencies": self.dependencies, "optional_dependencies": self.optional_dependencies,
            "capabilities": self.capabilities, "critical": self.critical,
        }


def metadata(**kwargs: Any) -> PluginMetadata:
    """Construct validated metadata matching the runtime contract."""
    return PluginMetadata(**kwargs)


__all__ = ["SDK_API_VERSION", "PluginMetadata", "metadata"]
