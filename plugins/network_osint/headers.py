import re
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.net import get_session
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}headers(?:\s+(\S+))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_headers,
        category="network_osint",
        description="Inspect HTTP response headers. Usage: .headers <url>"
    )

async def handle_headers(event):
    url = event.pattern_match.group(1)
    if not url:
        raise CommandError("Please provide a URL. Usage: .headers <url>")

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    session = get_session()
    try:
        async with session.head(url, allow_redirects=True) as resp:
            status_code = resp.status
            headers_dict = dict(resp.headers)
    except Exception as e:
        raise CommandError(f"Failed to reach {url}: {e}")

    rows = [
        f"Target: {url}",
        f"Status: {status_code}",
        "---"
    ]

    priority_headers = [
        "server",
        "content-type",
        "content-length",
        "strict-transport-security",
        "content-security-policy",
        "x-frame-options",
        "x-xss-protection",
        "x-content-type-options",
        "cf-ray"
    ]

    added = set()
    for key in priority_headers:
        for h_k, h_v in headers_dict.items():
            if h_k.lower() == key and h_k.lower() not in added:
                val = h_v[:45] + "..." if len(h_v) > 45 else h_v
                rows.append(f"{h_k}: {val}")
                added.add(h_k.lower())

    for h_k, h_v in headers_dict.items():
        if h_k.lower() not in added and len(rows) < 15:
            val = h_v[:45] + "..." if len(h_v) > 45 else h_v
            rows.append(f"{h_k}: {val}")
            added.add(h_k.lower())

    await event.edit(render(
        title="HTTP HEADERS",
        rows=rows,
        footer="network_osint | headers"
    ))
