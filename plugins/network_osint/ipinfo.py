import json
import re
from urllib.parse import quote

from core.context import get_application_context
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}ip(?:\s+(\S+))?$"
_MAX_TARGET = 253

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_ip,
        category="network_osint",
        description="Lookup IP/Host geolocation & ASN info. Usage: .ip [ip/domain]"
    )

async def handle_ip(event):
    target = (event.pattern_match.group(1) or "").strip()
    if len(target) > _MAX_TARGET:
        raise CommandError("IP/domain target is too long.")
    if any(char.isspace() for char in target):
        raise CommandError("IP/domain target must not contain whitespace.")

    context = get_application_context()
    if context is None:
        raise CommandError("HTTP service is unavailable.")
    http = context.get("http")

    url = f"http://ip-api.com/json/{quote(target, safe='')}"
    params = {
        "fields": "status,message,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
    }

    try:
        response = await http.get(url, params=params, response_limit=256 * 1024)
        if response.status != 200:
            raise CommandError(f"IP API query failed with HTTP {response.status}")
        data = json.loads(response.body)
    except CommandError:
        raise
    except Exception as exc:
        raise CommandError("Failed to fetch IP details.") from exc

    if data.get("status") != "success":
        err_msg = data.get("message", "Invalid IP/domain")
        raise CommandError(f"Lookup failed: {err_msg}")

    rows = [
        f"Query: {data.get('query')}",
        f"Location: {data.get('city')}, {data.get('regionName')}, {data.get('country')}",
        f"Coordinates: {data.get('lat')}, {data.get('lon')}",
        f"Timezone: {data.get('timezone')}",
        "---",
        f"ISP: {data.get('isp')}",
        f"Org: {data.get('org')}",
        f"ASN: {data.get('as')}"
    ]

    await event.edit(render(
        title="IP GEOLOCATION",
        rows=rows[:20],
        footer="network_osint | ip"
    ))
