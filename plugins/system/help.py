import os
import re
import html
from pathlib import Path
from telethon import events
from core.registry import register_cmd, COMMANDS
from helpers.hud import render
from config import config

BUILD = "Astra Command Manual · 2026.08"

PATTERN = rf"^{re.escape(config.PREFIX)}help(?:\s+(.*))?$"

CATEGORY_MAP = {
    "security": "◈ SECURITY & FORENSICS",
    "stealth": "◈ SECURITY & FORENSICS",
    "crypto": "◈ SECURITY & FORENSICS",
    "backup": "◈ CLOUD & STORAGE",
    "storage": "◈ CLOUD & STORAGE",
    "network_osint": "◈ OSINT & RECON",
    "advanced": "◈ OSINT & RECON",
    "ai": "◈ AI & MEDIA FLOW",
    "media": "◈ AI & MEDIA FLOW",
    "media_ops": "◈ AI & MEDIA FLOW",
    "system": "◈ SYSTEM OPS",
    "system_ops": "◈ SYSTEM OPS",
    "admin_ops": "◈ SYSTEM OPS",
    "fun": "◈ SYSTEM OPS"
}

MANUAL_DATABASE = {
    "testall": {
        "description": "Non-destructive Astra-wide self-test. Verifies Python syntax, command registry, optional binaries, safe handler registration, and Telegram/network reachability. Mutating commands are classified and skipped.",
        "usage": f"{config.PREFIX}testall [safe|report|network|static]",
        "subcommands": {
            "safe": "Run static checks plus the live Telegram/network probe and safe handler registration checks.",
            "report": "Default comprehensive report; writes a timestamped JSON report to data/logs/.",
            "network": "Focus on the live Telegram MTProto, DNS, and network side.",
            "static": "Focus on Python syntax/plugin and registry-level checks without network calls."
        },
        "examples": [f"{config.PREFIX}testall", f"{config.PREFIX}testall network", f"{config.PREFIX}testall static"]
    },
    "ask": {"description": "AI prompt interface.", "usage": f"{config.PREFIX}ask <prompt>", "subcommands": {}, "examples": []},
    "summarize": {"description": "Summarize text or replied messages.", "usage": f"{config.PREFIX}summarize [reply]", "subcommands": {}, "examples": []},
    "transcribe": {"description": "Transcribe replied audio or voice notes.", "usage": f"{config.PREFIX}transcribe [reply]", "subcommands": {}, "examples": []},
}


def _fallback_manual(name: str) -> dict:
    return {
        "description": "Registered AstraUserbot command.",
        "usage": f"{config.PREFIX}{name}",
        "subcommands": {},
        "examples": [f"{config.PREFIX}{name}"],
    }


async def setup(client):
    register_cmd(client, PATTERN, handle_help, "system", "Display the AstraUserbot command manual.")


async def handle_help(event):
    query = (event.pattern_match.group(1) or "").strip().lower()
    if query:
        entry = MANUAL_DATABASE.get(query) or _fallback_manual(query)
        rows = [entry["description"], "", f"Usage: {entry['usage']}"]
        if entry.get("subcommands"):
            rows.extend(f"• {key}: {value}" for key, value in entry["subcommands"].items())
        if entry.get("examples"):
            rows.extend(["", "Examples:", *entry["examples"]])
        await event.edit(render("ASTRA // HELP", rows, footer="system | help"))
        return

    grouped: dict[str, list[str]] = {}
    for pattern, meta in COMMANDS.items():
        category = meta.get("category", "system")
        grouped.setdefault(CATEGORY_MAP.get(category, category.upper()), []).append(pattern)

    rows = [f"{BUILD}", ""]
    for category, patterns in sorted(grouped.items()):
        rows.append(category)
        rows.extend(f"  {pattern}" for pattern in sorted(patterns))
        rows.append("")
    await event.edit(render("ASTRA // COMMAND MANUAL", rows[:120], footer="system | help"))
