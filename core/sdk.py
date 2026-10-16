"""Compatibility import path for the public plugin SDK.

New plugins should import from :mod:`astra.sdk`. The public facade owns the
validated metadata adapter; this module intentionally defines no duplicate
metadata schema.
"""
from astra.sdk import SDK_API_VERSION, PluginMetadata, metadata

__all__ = ["SDK_API_VERSION", "PluginMetadata", "metadata"]
