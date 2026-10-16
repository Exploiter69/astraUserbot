from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Protocol

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_public_sdk_imports_and_all_exports_resolve() -> None:
    sdk = importlib.import_module("astra.sdk")
    assert sdk.__all__
    assert len(sdk.__all__) == len(set(sdk.__all__))
    for name in sdk.__all__:
        assert hasattr(sdk, name), name
    assert "ApplicationContext" not in sdk.__all__
    assert not any("PluginManager" in name for name in sdk.__all__)


def test_metadata_defaults_and_runtime_normalization_match() -> None:
    sdk = importlib.import_module("astra.sdk")
    from core.plugins.contract import metadata_for

    declared = sdk.metadata(
        name="sample_plugin",
        version="2.3.4",
        api_version=sdk.SDK_API_VERSION,
        description="A sample plugin",
        dependencies=("alpha",),
        optional_dependencies=("beta",),
        capabilities=("telegram.read",),
        critical=True,
    )
    assert declared.name == "sample_plugin"
    assert declared.version == "2.3.4"
    assert declared.api_version == 1
    assert declared.description == "A sample plugin"
    assert declared.dependencies == ("alpha",)
    assert declared.optional_dependencies == ("beta",)
    assert declared.capabilities == ("telegram.read",)
    assert declared.critical is True

    module = ModuleType("sample_plugin")
    for field, value in declared.to_module_metadata().items():
        setattr(module, field, value)
    normalized = metadata_for(module)
    assert normalized == declared.to_runtime_contract()

    defaults = sdk.metadata(name="defaults")
    assert defaults.version == "legacy"
    assert defaults.api_version == 1
    assert defaults.description == ""
    assert defaults.dependencies == ()
    assert defaults.optional_dependencies == ()
    assert defaults.capabilities == ()
    assert defaults.critical is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": ""},
        {"name": "x" * 257},
        {"version": ""},
        {"version": "v" * 65},
        {"api_version": 999},
        {"description": "d" * 513},
        {"dependencies": ("",)},
        {"dependencies": ("x", "x")},
        {"capabilities": ("telegram.read", "telegram.read")},
        {"capabilities": ("not.a.capability",)},
        {"critical": "yes"},
    ],
)
def test_metadata_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    sdk = importlib.import_module("astra.sdk")
    values: dict[str, object] = {"name": "valid"}
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        sdk.metadata(**values)


def test_capability_types_are_the_existing_vocabulary_only() -> None:
    sdk = importlib.import_module("astra.sdk")
    from core.plugins.capabilities import CAPABILITIES, validate_capabilities

    assert set(sdk.CAPABILITY_NAMES) == set(CAPABILITIES)
    assert len(sdk.CAPABILITY_NAMES) == 11
    assert sdk.validate_capabilities(("telegram.read", "jobs.enqueue")) == (
        "telegram.read",
        "jobs.enqueue",
    )
    with pytest.raises(ValueError, match="Unknown capabilities"):
        sdk.validate_capabilities(("made.up.capability",))
    assert set(sdk.CapabilityMode) == {"ENFORCED", "LEGACY_UNDECLARED"}


def test_plugin_protocol_is_structural() -> None:
    sdk = importlib.import_module("astra.sdk")

    class SamplePlugin:
        plugin_name = "sample"
        plugin_version = "1.0"
        plugin_api_version = 1
        dependencies: tuple[str, ...] = ()
        optional_dependencies: tuple[str, ...] = ()
        capabilities = ("telegram.read",)
        description = "sample"
        critical = False

        def setup(self, client: object) -> None:
            self.client = client

    plugin = SamplePlugin()
    assert getattr(sdk.Plugin, "_is_protocol", False)
    assert all(
        hasattr(plugin, name)
        for name in (
            "setup", "plugin_name", "plugin_version", "plugin_api_version",
            "dependencies", "optional_dependencies", "capabilities",
            "description", "critical",
        )
    )
    assert callable(plugin.setup)


def test_docs_check_accepts_consistent_sdk_and_rejects_missing_symbol(
    tmp_path: Path,
) -> None:
    from tools.docs_check import validate_sdk_docs

    sdk = importlib.import_module("astra.sdk")
    docs = tmp_path / "PLUGIN_SDK.md"
    docs.write_text(
        "# Plugin SDK\n\n"
        f"SDK_API_VERSION: {sdk.SDK_API_VERSION}\n\n"
        "## API Reference\n\n"
        + "\n".join(f"- `{name}`" for name in sdk.__all__)
        + "\n",
        encoding="utf-8",
    )
    assert validate_sdk_docs(tmp_path) == []

    docs.write_text(
        docs.read_text(encoding="utf-8") + "\n- `definitely_missing_sdk_symbol`\n",
        encoding="utf-8",
    )
    findings = validate_sdk_docs(tmp_path)
    assert any("definitely_missing_sdk_symbol" in item for item in findings)


def test_plugin_is_a_structural_protocol_not_a_base_class() -> None:
    sdk = importlib.import_module("astra.sdk")
    assert getattr(sdk.Plugin, "_is_protocol", False)
    assert not any(base.__name__ == "ABC" for base in sdk.Plugin.__mro__)
