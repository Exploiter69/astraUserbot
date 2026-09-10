import re
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.net import get_session
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}ip(?:\s+(\S+))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_ip,
        category="network_osint",
        description="Lookup IP/Host geolocation & ASN info. Usage: .ip [ip/domain]"
    )

async def handle_ip(event):
    target = event.pattern_match.group(1) or ""
    session = get_session()
    url = f"http://ip-api.com/json/{target}?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,query"

    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise CommandError(f"IP API query failed with HTTP {resp.status}")
            data = await resp.json()
    except Exception as e:
        raise CommandError(f"Failed to fetch IP details: {e}")

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
        rows=rows,
        footer="network_osint | ip"
    ))
