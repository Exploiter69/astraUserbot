import os
import json
import re
import html
from pathlib import Path
from telethon import events
from core.registry import register_cmd, COMMANDS
from core.context import get_application_context
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
    # ----------------------------------------------------
    # ◈ AI & MEDIA FLOW
    # ----------------------------------------------------
    "ask": {
        "description": "AI prompt interface running Groq LLaMA-3 high-speed inference.",
        "usage": f"{config.PREFIX}ask <prompt>",
        "subcommands": {
            "<prompt>": "Submit query to LLaMA-3 and return formatted markdown analysis.",
            "(reply) <prompt>": "Use replied message content as contextual reference for the prompt."
        },
        "examples": [
            f"{config.PREFIX}ask Explain zero-knowledge proofs in 3 sentences.",
            f"{config.PREFIX}ask (as reply) Refactor this code to use async/await."
        ]
    },
    "summarize": {
        "description": "Generates a structured bulleted summary of long articles, chat logs, or text messages.",
        "usage": f"{config.PREFIX}summarize [reply]",
        "subcommands": {
            "(reply)": "Processes replied text, extracts key takeaways, and formats an executive summary."
        },
        "examples": [
            f"{config.PREFIX}summarize (as reply to long wall of text)"
        ]
    },
    "transcribe": {
        "description": "Transcribes speech from audio/voice notes via OpenAI Whisper cloud pipeline.",
        "usage": f"{config.PREFIX}transcribe [reply]",
        "subcommands": {
            "(reply)": "Converts replied Telegram voice note or audio file into clean plaintext."
        },
        "examples": [
            f"{config.PREFIX}transcribe (as reply to a voice note)"
        ]
    },
    "autopost": {
        "description": "Automated message scheduling and recurring broadcast dispatcher for chats/channels.",
        "usage": f"{config.PREFIX}autopost [add|list|rm|clear] [interval] [message]",
        "subcommands": {
            "add <interval_m> <text>": "Schedule a recurring post every N minutes in the current chat.",
            "list": "Display all active scheduled automated posts and their job IDs.",
            "rm <job_id>": "Cancel and remove a specific scheduled auto-post job.",
            "clear": "Stop and delete all active auto-posts across all chats."
        },
        "examples": [
            f"{config.PREFIX}autopost add 60 Reminder: Check daily server metrics.",
            f"{config.PREFIX}autopost list",
            f"{config.PREFIX}autopost rm job_04"
        ]
    },
    "ff": {
        "description": "FFmpeg and FFprobe media processing workbench.",
        "usage": f"{config.PREFIX}ff <probe|compress|gif|speed> [args]",
        "subcommands": {
            "probe": "Inspect codec, bitrate, stream containers, and audio tracks.",
            "compress [crf]": "Compress video using libx264/crf (Default: crf 28).",
            "gif": "Convert video segment to looping lightweight animated GIF.",
            "speed <0.5-2.0>": "Adjust playback speed of video or audio."
        },
        "examples": [
            f"{config.PREFIX}ff probe (as reply to video)",
            f"{config.PREFIX}ff gif (as reply to short clip)",
            f"{config.PREFIX}ff compress 30"
        ]
    },
    "ocr": {
        "description": "Optical Character Recognition using Tesseract OCR engine.",
        "usage": f"{config.PREFIX}ocr [reply]",
        "subcommands": {
            "(reply)": "Scans image/document attachment and outputs extracted text into chat."
        },
        "examples": [
            f"{config.PREFIX}ocr (as reply to screenshot or photo)"
        ]
    },
    "rclone": {
        "description": "Direct interface with system Rclone binary for remote cloud storage operations.",
        "usage": f"{config.PREFIX}rclone <copy|sync|ls|size|check> <source> <dest>",
        "subcommands": {
            "copy <src> <dest>": "Copy files/directories between local filesystem and remote cloud.",
            "sync <src> <dest>": "Make source and dest identical, modifying destination only.",
            "ls <remote:path>": "List objects in the specified remote directory.",
            "size <remote:path>": "Calculate total data size and object count on remote."
        },
        "examples": [
            f"{config.PREFIX}rclone copy data/ teldrive-crypt:astra_main/data/",
            f"{config.PREFIX}rclone ls teldrive-crypt:astra_main/"
        ]
    },
    "tts": {
        "description": "Neural Text-To-Speech engine converting text prompts into high-fidelity voice notes.",
        "usage": f"{config.PREFIX}tts [lang_code] <text | reply>",
        "subcommands": {
            "<text>": "Convert text into voice note using default voice (en).",
            "<lang> <text>": "Specify language code (e.g. en, hi, es, ja, de).",
            "(reply)": "Convert replied text message into spoken voice note."
        },
        "examples": [
            f"{config.PREFIX}tts Mission protocol initiated. All systems operational.",
            f"{config.PREFIX}tts hi नमस्ते दुनिया, सिस्टम ऑनलाइन है।",
            f"{config.PREFIX}tts (as reply to a message)"
        ]
    },
    "rip": {
        "description": "Universal stream and media extractor powered by yt-dlp.",
        "usage": f"{config.PREFIX}rip <audio|video|doc|best> <URL>",
        "subcommands": {
            "audio <URL>": "Extract and stream audio at highest bitrate (320kbps MP3/M4A).",
            "video <URL>": "Download video up to 1080p and upload with native streaming metadata.",
            "best <URL>": "Download highest available resolution and stream straight to chat."
        },
        "examples": [
            f"{config.PREFIX}rip video https://youtu.be/dQw4w9WgXcQ",
            f"{config.PREFIX}rip audio https://soundcloud.com/artist/track"
        ]
    },
    "round": {
        "description": "Transforms standard videos into Telegram circular video notes (Telescope format).",
        "usage": f"{config.PREFIX}round [reply]",
        "subcommands": {
            "(reply)": "Crops, centers, and re-encodes replied video to a 1:1 circular video message."
        },
        "examples": [
            f"{config.PREFIX}round (as reply to square or landscape video)"
        ]
    },

    # ----------------------------------------------------
    # ◈ CLOUD & STORAGE
    # ----------------------------------------------------
    "backup": {
        "description": "Compresses local databases, media cache, and configs, and pushes encrypted backups to Rclone remote.",
        "usage": f"{config.PREFIX}backup [now|status|remote|list]",
        "subcommands": {
            "now": "Trigger an immediate snapshot, compression, and encrypted cloud upload.",
            "status": "Check timestamp and size of the last successful backup job.",
            "remote <name>": "Set default Rclone crypt target remote (Default: teldrive-crypt).",
            "list": "Query remote cloud storage for available backup snapshots."
        },
        "examples": [
            f"{config.PREFIX}backup now",
            f"{config.PREFIX}backup status"
        ]
    },

    # ----------------------------------------------------
    # ◈ OSINT & RECON
    # ----------------------------------------------------
    "mediaflow": {
        "description": "Advanced media processing pipeline for batch conversion, stripping, and audio extraction.",
        "usage": f"{config.PREFIX}mediaflow <compress|extract|square|mute> [reply]",
        "subcommands": {
            "compress": "Lossless re-encode optimized for mobile bandwidth.",
            "extract": "Strip and export raw audio track from replied video.",
            "square": "Pad or crop replied media into a strict 1:1 aspect ratio.",
            "mute": "Remove all audio streams from video."
        },
        "examples": [
            f"{config.PREFIX}mediaflow extract (as reply to video)",
            f"{config.PREFIX}mediaflow mute (as reply to video)"
        ]
    },
    "osint": {
        "description": "Automated username scanner and digital footprint hunter across 50+ social platforms.",
        "usage": f"{config.PREFIX}osint <username>",
        "subcommands": {
            "<username>": "Concurrent asynchronous scan across GitHub, Twitter, Instagram, Reddit, TikTok, etc."
        },
        "examples": [
            f"{config.PREFIX}osint target_alias",
            f"{config.PREFIX}osint developer69"
        ]
    },
    "qnote": {
        "description": "Ultra-fast plaintext ephemeral scratchpad for rapid clipboard storage.",
        "usage": f"{config.PREFIX}qnote [set|get|list|del] [tag] [text]",
        "subcommands": {
            "<tag> <text>": "Save instant snippet under designated tag name.",
            "get <tag> (or .qget <tag>)": "Retrieve and display snippet content.",
            "list (or .qlist)": "List all active quick-note tags.",
            "del <tag>": "Delete specified snippet from cache."
        },
        "examples": [
            f"{config.PREFIX}qnote proxy http://127.0.0.1:8080",
            f"{config.PREFIX}qget proxy",
            f"{config.PREFIX}qlist"
        ]
    },
    "dns": {
        "description": "Performs DNS lookups over HTTPS (DoH) via Cloudflare/Google endpoints.",
        "usage": f"{config.PREFIX}dns <domain> [type]",
        "subcommands": {
            "<domain> A": "Lookup IPv4 address records (default).",
            "<domain> AAAA": "Lookup IPv6 address records.",
            "<domain> MX": "Inspect mail exchange routing records.",
            "<domain> TXT": "Read SPF, DKIM, and verification records."
        },
        "examples": [
            f"{config.PREFIX}dns google.com A",
            f"{config.PREFIX}dns cloudflare.com TXT"
        ]
    },
    "headers": {
        "description": "Fetches and analyzes HTTP response headers from remote servers.",
        "usage": f"{config.PREFIX}headers <url>",
        "subcommands": {
            "<url>": "Inspect HTTP status codes, caching headers, Cloudflare headers, and SSL security flags."
        },
        "examples": [
            f"{config.PREFIX}headers https://telegram.org"
        ]
    },
    "ip": {
        "description": "Geolocation, ISP, AS-Number, and reverse DNS lookup for IP/Domain.",
        "usage": f"{config.PREFIX}ip [target]",
        "subcommands": {
            "<ip/domain>": "Inspect geographic coordinates, ISP organization, ASN, and country flags.",
            "(none)": "Display external IP telemetry for the host running Astra."
        },
        "examples": [
            f"{config.PREFIX}ip",
            f"{config.PREFIX}ip 8.8.8.8",
            f"{config.PREFIX}ip github.com"
        ]
    },
    "portscan": {
        "description": "Asynchronous multi-threaded TCP port scanner for network reconnaissance.",
        "usage": f"{config.PREFIX}portscan <host> [ports]",
        "subcommands": {
            "<host>": "Scan top 20 common service ports (21, 22, 80, 443, 3306, 8080, etc.).",
            "<host> <port1,port2>": "Scan explicitly specified comma-separated ports."
        },
        "examples": [
            f"{config.PREFIX}portscan 1.1.1.1",
            f"{config.PREFIX}portscan example.com 22,80,443,8080,9000"
        ]
    },
    "speedtest": {
        "description": "Runs a non-blocking Ookla Speedtest network bandwidth test.",
        "usage": f"{config.PREFIX}speedtest",
        "subcommands": {
            "(none)": "Measures ping latency, upload bandwidth, download bandwidth, and server ISP."
        },
        "examples": [
            f"{config.PREFIX}speedtest"
        ]
    },

    # ----------------------------------------------------
    # ◈ SECURITY & FORENSICS
    # ----------------------------------------------------
    "savenote": {
        "description": "AES-256-GCM Encrypted Notes Vault with authentication tag verification.",
        "usage": f"{config.PREFIX}savenote <add|view|list|del> [title] [content]",
        "subcommands": {
            "add <title> <content>": "Encrypts note with master AES key and commits to secure vault.",
            "view <title>": "Decrypts note temporarily inside a self-destructing HUD card.",
            "list": "View indexed encrypted titles without exposing body content.",
            "del <title>": "Securely wipe note record from database."
        },
        "examples": [
            f"{config.PREFIX}savenote add seed_phrase word1 word2 word3 word4",
            f"{config.PREFIX}savenote view seed_phrase",
            f"{config.PREFIX}savenote list"
        ]
    },
    "arch": {
        "description": "Universal forensic chat and DM archiver with local SQLite full-text indexing.",
        "usage": f"{config.PREFIX}arch <status|stats|search|export> [query]",
        "subcommands": {
            "status [on|off]": "Toggle automated background archiving for all incoming/outgoing messages.",
            "stats": "Display total indexed entities, tracked users, and stored message counts.",
            "search <keyword>": "Perform rapid full-text SQL search across all saved logs.",
            "export [chat_id]": "Export conversation history as structured JSON/TXT."
        },
        "examples": [
            f"{config.PREFIX}arch status on",
            f"{config.PREFIX}arch stats",
            f"{config.PREFIX}arch search secret_key"
        ]
    },
    "track": {
        "description": "Selective watchlist tracking engine for monitoring specific high-value users in group chats.",
        "usage": f"{config.PREFIX}track <add|remove|list|clear> [user_id|reply]",
        "subcommands": {
            "add [user|reply]": "Add target user to the current group forensic watchlist.",
            "remove [user|reply]": "Remove target user from active monitoring.",
            "list": "Display all users currently under monitoring in this chat.",
            "clear": "Clear entire watchlist for the current chat."
        },
        "examples": [
            f"{config.PREFIX}track add (reply to user)",
            f"{config.PREFIX}track add @target_user",
            f"{config.PREFIX}track list"
        ]
    },
    "block": {
        "description": "Tactical contact blocking, unblocking, and blacklist enforcement manager.",
        "usage": f"{config.PREFIX}block [reason|reply|user_id] / {config.PREFIX}unblock [user_id]",
        "subcommands": {
            "(reply) [reason]": "Blocks replied user immediately and logs reason to forensic vault.",
            "<user_id>": "Directly block user by numeric ID or username without opening chat.",
            "unblock [user_id]": "Remove user from Telegram blacklist."
        },
        "examples": [
            f"{config.PREFIX}block Spammer detected (as reply)",
            f"{config.PREFIX}block @malicious_actor",
            f"{config.PREFIX}unblock @user_id"
        ]
    },
    "savevo": {
        "description": "Forensically captures self-destructing View-Once photos/videos and saves them permanently.",
        "usage": f"{config.PREFIX}savevo [reply]",
        "subcommands": {
            "(reply)": "Downloads expiring photo or video and sends a permanent copy to Saved Messages."
        },
        "examples": [
            f"{config.PREFIX}savevo (as reply to incoming view-once media)"
        ]
    },
    "hash": {
        "description": "Computes MD5, SHA-1, SHA-256, and SHA-512 checksums.",
        "usage": f"{config.PREFIX}hash <string | reply>",
        "subcommands": {
            "<text>": "Compute checksums for the provided plaintext string.",
            "(reply)": "Calculate file SHA-256 hash of replied document or image."
        },
        "examples": [
            f"{config.PREFIX}hash Password123!",
            f"{config.PREFIX}hash (as reply to file)"
        ]
    },
    "logger": {
        "description": "Forensic audit logger tracking edited and deleted messages in watched chats.",
        "usage": f"{config.PREFIX}logger [status|chat|dump|clear]",
        "subcommands": {
            "status": "Check active logging state and total retained forensic records.",
            "chat [on|off]": "Toggle forensic logging on/off for current chat specifically.",
            "dump": "Export raw edit/deletion history for current conversation.",
            "clear": "Flush local logger database cache."
        },
        "examples": [
            f"{config.PREFIX}logger status",
            f"{config.PREFIX}logger chat on",
            f"{config.PREFIX}logger dump"
        ]
    },
    "passgen": {
        "description": "Cryptographically secure random password and passphrase generator.",
        "usage": f"{config.PREFIX}passgen [length] [symbols:yes|no]",
        "subcommands": {
            "[length]": "Specify desired character length (Default: 16).",
            "[length] no": "Generate password without special symbols."
        },
        "examples": [
            f"{config.PREFIX}passgen 24",
            f"{config.PREFIX}passgen 12 no"
        ]
    },
    "pmpermit": {
        "description": "Private Message gatekeeper and anti-spam protection engine.",
        "usage": f"{config.PREFIX}pmpermit [approve|disapprove|block|setlimit|status] [user_id|reply]",
        "subcommands": {
            "approve / allow (or reply)": "Permit the target user to send direct messages without triggering warnings.",
            "disapprove / disallow (or reply)": "Revoke PM privileges. Re-activates spam warnings if they message again.",
            "block (or reply)": "Immediately ban and block the user from sending private messages.",
            "setlimit <count>": "Set maximum warning messages allowed before auto-blocking (Default: 4).",
            "status": "Check active gatekeeper state, spam counter status, and total authorized contacts."
        },
        "examples": [
            f"{config.PREFIX}pmpermit (as reply to incoming user DM)",
            f"{config.PREFIX}pmpermit approve @username",
            f"{config.PREFIX}pmpermit setlimit 3",
            f"{config.PREFIX}pmpermit status"
        ]
    },
    "vault": {
        "description": "AES-256-GCM encrypted key-value vault for storing private tokens, passwords, and sensitive keys.",
        "usage": f"{config.PREFIX}vault <set|get|rm|list|wipe> [key] [value]",
        "subcommands": {
            "set <key> <val>": "Encrypt and save an environment secret or credential token.",
            "get <key>": "Retrieve and decrypt the requested secret into a self-destruct HUD card.",
            "rm <key>": "Permanently delete the specified secret.",
            "list": "Display all stored key names without showing plaintext values.",
            "wipe": "Emergency purge of all stored encrypted keys."
        },
        "examples": [
            f"{config.PREFIX}vault set groq_token gsk_394829384",
            f"{config.PREFIX}vault get groq_token",
            f"{config.PREFIX}vault list"
        ]
    },
    "clone": {
        "description": "Stealth profile replication and identity spoofing engine.",
        "usage": f"{config.PREFIX}clone <target|revert|backup>",
        "subcommands": {
            "clone <reply|username>": "Extract target profile photo, first/last name, and bio, then apply to your account.",
            "revert": "Restore original profile snapshot from local identity storage.",
            "backup": "Save current profile state as default identity baseline."
        },
        "examples": [
            f"{config.PREFIX}clone (reply to any user)",
            f"{config.PREFIX}clone @durov",
            f"{config.PREFIX}clone revert"
        ]
    },

    # ----------------------------------------------------
    # ◈ SYSTEM OPS
    # ----------------------------------------------------
    "purge": {
        "description": "Fast bidirectional message purge utility for group chats and private DMs.",
        "usage": f"{config.PREFIX}purge [reply | count]",
        "subcommands": {
            "(reply)": "Purge all messages between replied message and current message.",
            "<count>": "Purge the last N messages sent in the chat."
        },
        "examples": [
            f"{config.PREFIX}purge (as reply to an earlier message)",
            f"{config.PREFIX}purge 15"
        ]
    },
    "mock": {
        "description": "Text transformation utility (sPoNgEbOb case, aesthetic spaced, vaporwave, reverse).",
        "usage": f"{config.PREFIX}mock <mode> <text | reply>",
        "subcommands": {
            "sponge <text>": "cOnVeRtS tExT tO sArCaSm CaSe.",
            "space <text>": "A E S T H E T I C  S P A C I N G.",
            "flip <text>": "Reverses order of characters.",
            "(reply)": "Applies transformation to replied message directly."
        },
        "examples": [
            f"{config.PREFIX}mock sponge you cannot do that",
            f"{config.PREFIX}mock space cyberdeck",
            f"{config.PREFIX}mock (as reply)"
        ]
    },
    "afk": {
        "description": "Automated status presence engine that replies to mentions/DMs when you are busy.",
        "usage": f"{config.PREFIX}afk [reason]",
        "subcommands": {
            "<reason>": "Enable AFK mode with custom reason message and timestamp.",
            "(none)": "Toggle AFK with default busy message.",
            "Sending any message": "Automatically disables AFK mode and displays time elapsed."
        },
        "examples": [
            f"{config.PREFIX}afk Studying for exams, will respond later.",
            f"{config.PREFIX}afk"
        ]
    },
    "eval": {
        "description": "Executes raw Python code asynchronously inside userbot runtime environment.",
        "usage": f"{config.PREFIX}eval <code>",
        "subcommands": {
            "<code>": "Execute statement or expression with stdout/stderr capture and runtime telemetry."
        },
        "examples": [
            f"{config.PREFIX}eval await client.get_dialogs()",
            f"{config.PREFIX}eval import sys; sys.version"
        ]
    },
    "doctor": {
        "description": "Automated system diagnostics, database health verification, and dependency auditing.",
        "usage": f"{config.PREFIX}doctor [fix]",
        "subcommands": {
            "(none)": "Runs full audit on disk, database locks, API endpoints, and binary dependencies.",
            "fix": "Attempts automatic remediation of broken locks or stale cache."
        },
        "examples": [
            f"{config.PREFIX}doctor",
            f"{config.PREFIX}doctor fix"
        ]
    },
    "ping": {
        "description": "Measures MTProto gateway round-trip time and system load.",
        "usage": f"{config.PREFIX}ping",
        "subcommands": {
            "(none)": "Calculates millisecond latency, CPU usage, and memory consumption."
        },
        "examples": [
            f"{config.PREFIX}ping"
        ]
    },
    "sysinfo": {
        "description": "Comprehensive host OS, kernel, uptime, and system hardware metrics.",
        "usage": f"{config.PREFIX}sysinfo",
        "subcommands": {
            "(none)": "Displays Linux kernel version, uptime, architecture, CPU load, and RAM."
        },
        "examples": [
            f"{config.PREFIX}sysinfo"
        ]
    }
}

def _extract_command_names(pattern: str) -> list[str]:
    raw = pattern.replace(f"^{re.escape(config.PREFIX)}", "")
    raw = raw.split("(?")[0].replace("$", "").replace("\\", "")
    if raw.startswith("(") and raw.endswith(")"):
        return raw.strip("()").split("|")
    elif "(" in raw and ")" in raw:
        core = re.search(r'\((.*?)\)', raw)
        if core:
            return core.group(1).split("|")
    return [raw] if raw else []

def _command_names_from_pattern(pattern: str) -> list[str]:
    raw = pattern.replace(f"^{re.escape(config.PREFIX)}", "")
    raw = raw.split("(?")[0].replace("$", "").replace("\\", "")
    if raw.startswith("(") and raw.endswith(")"):
        return [x for x in raw.strip("()").split("|") if x]
    match = re.search(r"\(([^)]+)\)", pattern)
    if match:
        return [x for x in match.group(1).split("|") if not x.startswith("?") and x]
    return [raw] if raw else []



def _effective_doc(name: str, meta: dict) -> dict:
    doc = dict(MANUAL_DATABASE.get(name, {}))
    doc.setdefault("description", meta.get("description", "No description provided."))
    doc.setdefault("usage", f"{config.PREFIX}{name}")
    doc.setdefault("subcommands", {})
    doc.setdefault("examples", [doc["usage"]])
    return doc


def _risk_for_command(name: str) -> str:
    destructive = {
        "purge", "purgeme", "zombies", "promote", "demote", "slow", "kickme",
        "block", "unblock", "clone", "revert", "savevo", "arch", "track",
        "pmpermit", "backup", "autopost", "cleancache", "update", "vault",
        "savenote", "delnote_sec", "logger", "mirror", "setlogger", "read"
    }
    external = {"rip", "rclone", "aria", "ff", "mediaflow", "round", "ocr", "tts", "transcribe", "osint", "speedtest"}
    if name in destructive:
        return "MUTATING"
    if name in external:
        return "EXTERNAL"
    return "SAFE"


def _usage_from_pattern(pattern: str, primary: str) -> str:
    """Best-effort syntax derived from the live Telethon regex."""
    text = pattern.replace(f"^{re.escape(config.PREFIX)}", f"{config.PREFIX}").replace("$", "")
    text = text.replace("(?:", "[").replace(")?", "]").replace("(.*)", "<args>").replace("(\\S+)", "<value>")
    text = re.sub(r"\\[.\\]", ".", text)
    text = re.sub(r"\\s\+", " ", text)
    text = text.replace("(?:", "[")
    if text.endswith("?"):
        text = text[:-1]
    return text or f"{config.PREFIX}{primary}"


def _manual_intro() -> list[str]:
    return [
        f"{BUILD}",
        "Interactive reference for the commands actually registered at startup.",
        "Use .help <command> for a focused card; use .help -m for the full manual.",
        "Legend: SAFE = local/read-only · EXTERNAL = network/tool dependent · MUTATING = changes state.",
        "",
    ]

def _build_command_index() -> dict:
    index = {v: [] for v in set(CATEGORY_MAP.values())}
    index["◈ UNCATEGORIZED"] = []
    for pattern, meta in COMMANDS.items():
        raw_cat = meta.get("category", "system")
        mapped_cat = CATEGORY_MAP.get(raw_cat, "◈ UNCATEGORIZED")
        index[mapped_cat].extend(_command_names_from_pattern(pattern))
    return {k: sorted(set(v), key=str.lower) for k, v in index.items() if v}


def _generate_standalone_html() -> str:
    categorized = {}
    for pattern, meta in COMMANDS.items():
        category = CATEGORY_MAP.get(meta.get("category", "system"), "◈ UNCATEGORIZED")
        for name in _command_names_from_pattern(pattern):
            categorized.setdefault(category, []).append((name, pattern, meta))

    parts = ["""<!doctype html><html><head><meta charset="utf-8">
<title>Astra Userbot — Master Manual</title>
<style>
:root{color-scheme:dark}body{margin:0;background:#080b12;color:#d7deea;font:15px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace}
main{max-width:1050px;margin:auto;padding:38px 22px}h1{font-size:30px;margin:0 0 8px}h2{margin-top:34px;padding:10px 12px;border:1px solid #263044;border-radius:12px;background:#101624}
.card{border:1px solid #20293a;background:#0e131e;border-radius:14px;padding:18px;margin:14px 0}.name{font-size:19px;font-weight:800}.pill{display:inline-block;padding:2px 8px;border:1px solid #34405a;border-radius:999px;margin-left:8px;font-size:11px}.desc{color:#aeb9cb}.code{background:#080b12;border:1px solid #1e2737;padding:10px;border-radius:9px;white-space:pre-wrap}.label{color:#71809a}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:700px){.grid{grid-template-columns:1fr}}
ul{margin-top:5px}footer{margin-top:40px;color:#6f7c92}
</style></head><body><main>
<h1>⚡ ASTRA // MASTER MANUAL</h1>
<p>""" + BUILD + """<br>Live command registry + detailed usage reference.</p>
<div class="card"><b>Navigation</b><br><span class="code">.help &lt;command&gt;</span> focused command card<br><span class="code">.help -m</span> complete manual<br><span class="code">.doctor</span> detailed health audit<br><span class="code">.testall</span> non-destructive command/system test</div>
"""]
    for category in sorted(categorized):
        parts.append(f"<h2>{html.escape(category)}</h2>")
        seen=set()
        for name, pattern, meta in sorted(categorized[category], key=lambda x:x[0].lower()):
            if name in seen: continue
            seen.add(name)
            doc=_effective_doc(name, meta)
            risk=_risk_for_command(name)
            usage=doc.get("usage") or _usage_from_pattern(pattern,name)
            parts.append('<div class="card">')
            parts.append(f'<div class="name">{html.escape(config.PREFIX+name)} <span class="pill">{risk}</span></div>')
            parts.append(f'<p class="desc">{html.escape(str(doc["description"]))}</p>')
            parts.append(f'<div class="label">SYNTAX</div><div class="code">{html.escape(str(usage))}</div>')
            sub=doc.get("subcommands") or {}
            ex=doc.get("examples") or []
            if sub:
                parts.append('<div class="grid"><div><div class="label">ARGUMENTS / ACTIONS</div><ul>')
                for a,d in sub.items(): parts.append(f'<li><b>{html.escape(str(a))}</b> — {html.escape(str(d))}</li>')
                parts.append('</ul></div>')
            if ex:
                if sub: parts.append('<div>')
                else: parts.append('<div class="grid"><div>')
                parts.append('<div class="label">EXAMPLES</div><ul>')
                for e in ex: parts.append(f'<li><span class="code">{html.escape(str(e))}</span></li>')
                parts.append('</ul></div></div>')
            elif sub:
                parts.append('</div>')
            parts.append('</div>')
    parts.append('<footer>Generated from the live Astra registry. Missing optional binaries are reported by .doctor / .testall.</footer></main></body></html>')
    return ''.join(parts)


async def _publish_telegraph_manual() -> str:
    nodes = [
        {"tag": "h3", "children": ["Astra Userbot // Master Operational Reference Manual"]},
        {"tag": "p", "children": ["Exhaustive command index, parameter syntax, subcommands, and practical examples."]},
        {"tag": "hr"}
    ]
    
    categorized_meta = {}
    for pattern, meta in COMMANDS.items():
        raw_cat = meta.get("category", "system")
        mapped_cat = CATEGORY_MAP.get(raw_cat, "◈ UNCATEGORIZED")
        categorized_meta.setdefault(mapped_cat, []).append((pattern, meta))

    for cat_name in sorted(categorized_meta.keys()):
        nodes.append({"tag": "h3", "children": [cat_name]})
        for pattern, item in categorized_meta[cat_name]:
            cmds = _extract_command_names(pattern)
            primary = cmds[0] if cmds else "cmd"
            doc = MANUAL_DATABASE.get(primary, {})
            desc_text = doc.get("description") or item.get("description", "No description provided.")
            usage_text = doc.get("usage") or item.get("usage", f"{config.PREFIX}{primary}")
            subcmds = doc.get("subcommands") or item.get("subcommands", {})
            examples = doc.get("examples") or item.get("examples", [])

            nodes.append({"tag": "h4", "children": [{"tag": "code", "children": [f"{config.PREFIX}{primary}"]}]})
            nodes.append({"tag": "p", "children": [{"tag": "b", "children": ["Description: "]}, desc_text]})
            nodes.append({"tag": "p", "children": [{"tag": "b", "children": ["Syntax: "]}, {"tag": "code", "children": [usage_text]}]})
            
            if subcmds:
                sub_items = [{"tag": "li", "children": [{"tag": "code", "children": [f"{s}"]}, f" — {d}"]} for s, d in subcmds.items()]
                nodes.append({"tag": "p", "children": [{"tag": "b", "children": ["Arguments & Subcommands:"]}]})
                nodes.append({"tag": "ul", "children": sub_items})
                
            if examples:
                ex_items = [{"tag": "li", "children": [{"tag": "code", "children": [ex]}]} for ex in examples]
                nodes.append({"tag": "p", "children": [{"tag": "b", "children": ["Practical Examples:"]}]})
                nodes.append({"tag": "ul", "children": ex_items})
                
            nodes.append({"tag": "hr"})

    context = get_application_context()
    if context is None:
        raise RuntimeError("Application context is unavailable.")

    http = context.get("http")

    account_response = await http.post(
        "https://api.telegra.ph/createAccount",
        data=json.dumps({
            "short_name": "Astra",
            "author_name": "Astra Engine",
        }),
        headers={"Content-Type": "application/json"},
        timeout=8,
        response_limit=128 * 1024,
    )

    acc_data = json.loads(account_response.text)
    token = acc_data.get("result", {}).get("access_token")

    if not token:
        raise RuntimeError("Failed to obtain Telegraph token.")

    page_response = await http.post(
        "https://api.telegra.ph/createPage",
        data=json.dumps({
            "access_token": token,
            "title": "Astra Userbot // Command Manual",
            "author_name": "Astra System",
            "content": nodes,
            "return_content": False,
        }),
        headers={"Content-Type": "application/json"},
        timeout=8,
        response_limit=256 * 1024,
    )

    res_json = json.loads(page_response.text)
    if not res_json.get("ok"):
        raise RuntimeError(
            f"Telegraph Error: {res_json.get('error', 'Unknown')}"
        )

    return res_json["result"]["url"]

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_help,
        category="system",
        description="Interactive hybrid help engine with Telegraph & offline manual generator."
    )

async def handle_help(event):
    query = (event.pattern_match.group(1) or "").strip()

    if query.lower() in {"-m", "manual", "--manual", "all"}:
        await event.edit(render("MANUAL // BUILDING", [
            f"{BUILD}",
            "Compiling the live command registry...",
            "Generating a detailed dark-theme reference...",
            "Trying Telegraph first; offline HTML is the fallback.",
        ], footer="system | manual"))
        try:
            url = await _publish_telegraph_manual()
            await event.edit(render("MANUAL // READY", [
                "Master manual published successfully ✓",
                f"Open: {url}",
                "Contains categories, syntax, arguments, examples and risk labels.",
                f"Local fallback: data/cache/Astra_Manual.html",
            ], footer="system | manual"))
            return
        except Exception as exc:
            logger = __import__('logging').getLogger("astra.help")
            logger.warning("Telegraph manual publish failed: %s", type(exc).__name__)
            html_content = _generate_standalone_html()
            cache_dir = Path("data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            manual_file = cache_dir / "Astra_Manual.html"
            manual_file.write_text(html_content, encoding="utf-8")
            await event.client.send_file(
                event.chat_id,
                file=str(manual_file),
                caption=render("MANUAL // OFFLINE", [
                    "Telegraph unavailable; local manual compiled ✓",
                    "Open the attached HTML in a browser.",
                    "It was generated from the live command registry.",
                ], footer="system | manual"),
                reply_to=event.id,
            )
            await event.delete()
            return

    if query:
        clean = query.lower().lstrip(config.PREFIX).split()[0]
        found = None
        primary = clean
        for pattern, meta in COMMANDS.items():
            names = _command_names_from_pattern(pattern)
            if clean in names:
                found = (pattern, meta)
                primary = clean
                break
        if not found:
            await event.edit(render("HELP // NOT FOUND", [
                f"No registered command matches: {clean}",
                f"Try: {config.PREFIX}help",
                f"Manual: {config.PREFIX}help -m",
            ], footer="system | help"))
            return
        pattern, meta = found
        doc = _effective_doc(primary, meta)
        category = CATEGORY_MAP.get(meta.get("category", "system"), "◈ UNCATEGORIZED")
        risk = _risk_for_command(primary)
        usage = doc.get("usage") or _usage_from_pattern(pattern, primary)
        rows = [
            f"Command: `{config.PREFIX}{primary}`",
            f"Category: `{category}`",
            f"Execution: `{risk}`",
            "---",
            str(doc["description"]),
            "---",
            f"Syntax: `{usage}`",
        ]
        sub = doc.get("subcommands") or {}
        if sub:
            rows += ["---", "**ARGUMENTS / ACTIONS**"]
            for arg, desc in sub.items(): rows.append(f"• `{arg}` — {desc}")
        examples = doc.get("examples") or []
        if examples:
            rows += ["---", "**EXAMPLES**"]
            for example in examples: rows.append(f"• `{example}`")
        rows += ["---", f"Full manual: `{config.PREFIX}help -m`"]
        await event.edit(render(f"HELP // {primary.upper()}", rows, footer=f"system | {category} | {risk.lower()}"))
        return

    index = _build_command_index()
    total = sum(len(items) for items in index.values())
    rows = _manual_intro() + [f"Registered commands: `{total}`", "---"]
    for category in sorted(index):
        rows.append(category)
        names = [f"`{config.PREFIX}{name}`" for name in index[category]]
        for i in range(0, len(names), 3): rows.append("  " + "  ".join(names[i:i+3]))
        rows.append("---")
    rows += [
        f"Inspect: `{config.PREFIX}help <cmd>`",
        f"Manual: `{config.PREFIX}help -m`",
        f"Health: `{config.PREFIX}doctor`",
        f"Test: `{config.PREFIX}testall`",
    ]
    await event.edit(render("ASTRA // COMMAND DECK", rows, footer="system | navigation"))

