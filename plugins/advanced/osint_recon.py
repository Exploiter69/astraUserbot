import asyncio
import re

from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}osint(?:\s+(\S+))?$"

PLATFORMS = {
    "GitHub": "https://github.com/{}",
    "Twitter": "https://twitter.com/{}",
    "Instagram": "https://instagram.com/{}",
    "Reddit": "https://reddit.com/r/{}",
    "Telegram": "https://t.me/{}",
    "TikTok": "https://www.tiktok.com/@{}",
    "Steam": "https://steamcommunity.com/id/{}"
}

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_osint,
        category="advanced",
        description="Scan username across public social platforms. Usage: .osint <username>"
    )

async def _check_profile(http, name: str, platform: str, url_template: str) -> tuple[str, bool]:
    url = url_template.format(name)
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    try:
        response = await http.get(url, headers=headers, allow_redirects=True, timeout=5, response_limit=64 * 1024)
        return platform, response.status == 200
    except Exception:
        return platform, False

async def handle_osint(event):
    username = event.pattern_match.group(1)
    if not username:
        raise CommandError("Please provide a username to scan. Usage: .osint <username>")

    context = get_application_context()
    if context is None:
        raise CommandError("HTTP service is unavailable.")
    http = context.get("http")

    await event.edit(render(
        title="OSINT RECON",
        rows=[f"Target: {username}", "Scanning public platforms..."],
        footer="advanced | osint"
    ))

    tasks = [_check_profile(http, username, platform, template) for platform, template in PLATFORMS.items()]
    results = await asyncio.gather(*tasks)

    rows = [f"Target: `{username}`", "---"]
    hits = 0
    for platform, found in results:
        status = "FOUND [✓]" if found else "NOT FOUND [x]"
        if found:
            hits += 1
        rows.append(f"{platform}: {status}")

    rows.append("---")
    rows.append(f"Summary: {hits}/{len(PLATFORMS)} matches found")

    await event.edit(render(
        title="OSINT RESULTS",
        rows=rows,
        footer="advanced | osint"
    ))
