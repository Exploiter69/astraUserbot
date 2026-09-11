from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SDK_API_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    name: str
    version: str = "1.0.0"
    api_version: str = SDK_API_VERSION
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.name or len(self.name) > 120:
            raise ValueError("Plugin name is required and bounded")
        if self.api_version.split(".")[0] != SDK_API_VERSION.split(".")[0]:
            raise ValueError(f"Unsupported plugin API version: {self.api_version}")
        if any(not item or len(item) > 120 for item in self.dependencies + self.optional_dependencies):
            raise ValueError("Plugin dependency names must be bounded")


def metadata(**kwargs: Any) -> PluginMetadata:
    value = PluginMetadata(**kwargs)
    value.validate()
    return value
