"""Generate .env.example from the audited runtime environment contract.

The explicit contract documents defaults and purpose; AST checks ensure names read
by config.py, core services, and plugins are not silently omitted. Legacy template
entries without consumers are recorded in ORPHANED_TEMPLATE_VARIABLES below.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# name: (default/example value, comment)
ENVIRONMENT_CONTRACT: dict[str, tuple[str, str]] = {
    "ASTRA_API_ID": ("", "Required Telegram API ID; preferred config.py name."),
    "API_ID": ("", "Legacy alias for ASTRA_API_ID."),
    "ASTRA_API_HASH": ("", "Required Telegram API hash; preferred config.py name."),
    "API_HASH": ("", "Legacy alias for ASTRA_API_HASH."),
    "ASTRA_OWNER_ID": ("", "Required numeric owner ID; preferred config.py name."),
    "OWNER_ID": ("", "Legacy alias for ASTRA_OWNER_ID."),
    "ASTRA_SESSION_NAME": ("astra_session", "Telethon file-session basename under data/."),
    "SESSION_NAME": ("astra_session", "Legacy alias for ASTRA_SESSION_NAME."),
    "ASTRA_PREFIX": (".", "Command prefix; preferred config.py name."),
    "PREFIX": (".", "Legacy alias for ASTRA_PREFIX."),
    "ASTRA_LOG_LEVEL": ("INFO", "Python logging level."),
    "ASTRA_SAFE_MODE": ("0", "Set to 1 to skip plugin initialization."),
    "GROQ_API_KEY": ("", "Optional Groq API credential."),
    "GEMINI_API_KEY": ("", "Optional Gemini API credential."),
    "RCLONE_REMOTE": ("teldrive-crypt:", "Configured rclone remote for cloud backup."),
    "ASTRA_VAULT_KEY": ("", "Master key for the encrypted local vault; keep private."),
    "ASTRA_ARCHIVE_RETENTION_DAYS": ("30", "Account-archive retention window in days."),
    "ASTRA_ARCHIVE_MAX_MESSAGES": ("100000", "Maximum retained account-archive messages."),
    "ASTRA_AI_PROVIDER": ("groq", "AI provider: groq, gemini, or ollama."),
    "ASTRA_AI_REMOTE_ENABLED": ("true", "Explicit opt-in switch for remote AI providers."),
    "ASTRA_AI_FALLBACKS": ("gemini,ollama", "Fallback provider order."),
    "ASTRA_AI_MAX_REMOTE_REQUESTS": ("100", "Remote AI request budget per window."),
    "ASTRA_AI_REMOTE_WINDOW_SECONDS": ("86400", "Remote AI budget window in seconds."),
    "ASTRA_AI_GROQ_MODEL": ("openai/gpt-oss-20b", "Groq model identifier."),
    "ASTRA_AI_GEMINI_MODEL": ("gemini-2.5-flash", "Gemini model identifier."),
    "ASTRA_AI_OLLAMA_MODEL": ("qwen2.5:7b", "Local Ollama model identifier."),
    "ASTRA_AI_OLLAMA_URL": ("http://127.0.0.1:11434/api", "Loopback Ollama API base URL."),
    "ASTRA_AI_TRANSCRIBE_MODEL": ("whisper-large-v3", "Audio transcription model identifier."),
    "ASTRA_AI_MAX_AUDIO_BYTES": ("104857600", "Maximum audio input size in bytes."),
}

# These were in the previous template but have no runtime consumer in config.py,
# core/, or plugins/. Keep this explicit until each is intentionally adopted or
# permanently removed from historical configuration guidance.
ORPHANED_TEMPLATE_VARIABLES = {
    "SESSION_STRING": "removed; client.py uses the Telethon file-session path under data/",
    "BOT_TOKEN": "no runtime consumer found",
    "BOT_API_KEY": "no runtime consumer found",
    "DATABASE_URL": "the application uses local SQLite, not this URL",
    "GITHUB_TOKEN": "no runtime consumer found",
}


def consumed_environment_names(root: Path = ROOT) -> set[str]:
    """Collect literal environment names read by runtime config/services."""
    source_paths = [root / "config.py"]
    for folder in (root / "core", root / "plugins"):
        source_paths.extend(sorted(folder.rglob("*.py")))

    names: set[str] = set()
    for path in source_paths:
        if not path.is_file() or any(
            part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts
        ):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_getenv = (
                isinstance(func, ast.Attribute)
                and func.attr == "getenv"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            )
            is_environ_get = (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
            )
            if (is_getenv or is_environ_get) and node.args:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    names.add(value.value)
            if (
                isinstance(func, ast.Name)
                and func.id in {"_required_int", "_required_text"}
                and path.name == "config.py"
            ):
                names.update(
                    arg.value for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                )
            # os.environ["NAME"] is another direct-read spelling.
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "os"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                names.add(node.slice.value)
    # AI model names are selected from a provider->environment-name map.
    names.update({
        "ASTRA_AI_GROQ_MODEL",
        "ASTRA_AI_GEMINI_MODEL",
        "ASTRA_AI_OLLAMA_MODEL",
    })
    return names


def contract_findings(root: Path = ROOT) -> list[str]:
    consumed = consumed_environment_names(root)
    missing = sorted(consumed - ENVIRONMENT_CONTRACT.keys())
    return [f"runtime environment variable missing from contract: {name}" for name in missing]


def render_env_example() -> str:
    sections = [
        "# Generated by tools/gen_env_example.py; do not hand-edit.",
        "# Telethon uses a file session at data/<ASTRA_SESSION_NAME>.session.",
        "# SESSION_STRING is not supported; authenticate using the file-session flow.",
        "",
        "# Runtime configuration and compatibility aliases",
    ]
    for name, (default, description) in ENVIRONMENT_CONTRACT.items():
        sections.append(f"# {description}")
        sections.append(f"{name}={default}")
        if name in {"API_HASH", "OWNER_ID", "SESSION_NAME", "PREFIX"}:
            sections.append("")
    sections.extend([
        "",
        "# Optional local vault, archive, and AI settings are listed above.",
        "# Keep credential values private; never commit a populated .env file.",
        "",
    ])
    return "\n".join(sections)


def main() -> int:
    findings = contract_findings()
    if findings:
        for finding in findings:
            print(f"FAIL: {finding}")
        return 1
    output = ROOT / ".env.example"
    output.write_text(render_env_example(), encoding="utf-8")
    print(f"Generated {output.relative_to(ROOT)} from {len(ENVIRONMENT_CONTRACT)} contract entries.")
    print(f"Orphaned legacy template variables (not generated): {', '.join(sorted(ORPHANED_TEMPLATE_VARIABLES))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
