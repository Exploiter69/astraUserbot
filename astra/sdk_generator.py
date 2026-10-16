"""Deterministic scaffold generator for AstraUserbot plugins.

Run with: python -m astra.sdk_generator create-plugin <name>
"""
from __future__ import annotations

import argparse
import keyword
import re
import shutil
import sys
import tempfile
from pathlib import Path

_PLUGIN_NAME = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_RESERVED_NAMES = frozenset({"__pycache__", "astra", "core", "tests"})
_TEMPLATE_FILES = {
    "__init__.py": "__init__.py.tmpl",
    "plugin.py": "plugin.py.tmpl",
    "README.md": "README.md.tmpl",
    "tests/test_plugin.py": "tests/test_plugin.py.tmpl",
}


def validate_plugin_name(name: str) -> str:
    """Validate a single, portable Python package-name component."""
    if not isinstance(name, str) or not _PLUGIN_NAME.fullmatch(name):
        raise ValueError(
            "plugin name must start with a lowercase letter and contain only "
            "lowercase letters, digits, or underscores (maximum 48 characters)"
        )
    if keyword.iskeyword(name) or name in _RESERVED_NAMES:
        raise ValueError(f"reserved plugin name: {name}")
    return name


def create_plugin(
    name: str, *, project_root: Path | str | None = None, force: bool = False
) -> Path:
    """Create a deterministic plugin scaffold under <project_root>/plugins/<name>."""
    name = validate_plugin_name(name)
    if not isinstance(force, bool):
        raise TypeError("force must be a boolean")
    root = Path(project_root if project_root is not None else Path.cwd()).resolve()
    plugins_root = root / "plugins"
    output = plugins_root / name
    if output.exists() and not force:
        raise FileExistsError(
            f"plugin output already exists: {output} (pass --force to overwrite)"
        )
    if output.exists() and not output.is_dir():
        raise FileExistsError(f"plugin output is not a directory: {output}")

    template_root = Path(__file__).resolve().parent / "templates" / "plugin"
    rendered: dict[str, str] = {}
    for destination, template_name in _TEMPLATE_FILES.items():
        template_path = template_root / template_name
        if not template_path.is_file():
            raise FileNotFoundError(f"plugin template is missing: {template_path}")
        template = template_path.read_text(encoding="utf-8")
        rendered[destination] = template.replace("{{PLUGIN_NAME}}", name).replace(
            "{{COMMAND_NAME}}", name.replace("_", "-")
        )

    # Stage all output before changing the target. A failed render/write cannot
    # leave a half-generated plugin in the runtime discovery tree.
    plugins_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{name}.stage-", dir=plugins_root))
    try:
        for relative, content in rendered.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\\n")
        if output.exists():
            if not force:
                raise FileExistsError(
                    f"plugin output appeared during generation: {output}"
                )
            shutil.rmtree(output)
        stage.replace(output)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m astra.sdk_generator",
        description="Generate an AstraUserbot plugin scaffold.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser(
        "create-plugin", help="create plugins/<name>/"
    )
    create_parser.add_argument("name", help="lowercase Python package-name component")
    create_parser.add_argument(
        "--force", action="store_true", help="replace an existing generated plugin"
    )
    args = parser.parse_args(argv)
    try:
        output = create_plugin(args.name, force=args.force)
    except (ValueError, FileExistsError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(output.relative_to(Path.cwd().resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
