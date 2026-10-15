import ast
from pathlib import Path

from tools.gen_env_example import (
    ENVIRONMENT_CONTRACT,
    ROOT,
    contract_findings,
    render_env_example,
)


def _config_environment_names() -> set[str]:
    tree = ast.parse((ROOT / "config.py").read_text(encoding="utf-8"))
    config_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Config"
    )
    names: set[str] = set()
    for node in config_class.body:
        value = getattr(node, "value", None)
        if value is None:
            continue
        for child in ast.walk(value):
            if (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child.value in ENVIRONMENT_CONTRACT
            ):
                names.add(child.value)
    return names


def test_generated_env_example_matches_committed_template():
    assert (ROOT / ".env.example").read_text(encoding="utf-8") == render_env_example()


def test_generated_template_covers_config_py_environment_fields():
    generated = render_env_example()
    for name in _config_environment_names():
        assert f"{name}=" in generated, f"{name} missing from generated template"


def test_environment_contract_covers_literal_runtime_consumers():
    assert contract_findings(ROOT) == []
