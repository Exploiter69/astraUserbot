import re
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from helpers.net import get_session
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}dns(?:\s+(\S+))?(?:\s+(\S+))?$"

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_dns,
        category="network_osint",
        description="Query DNS records over HTTPS (DoH). Usage: .dns <domain> [type]"
    )

async def handle_dns(event):
    domain = event.pattern_match.group(1)
    record_type = (event.pattern_match.group(2) or "A").upper()
    
    if not domain:
        raise CommandError("Please provide a domain. Usage: .dns <domain> [A|AAAA|MX|TXT|NS|CNAME]")

    session = get_session()
    url = f"https://cloudflare-dns.com/dns-query?name={domain}&type={record_type}"
    headers = {"Accept": "application/dns-json"}
    
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                raise CommandError(f"DNS query failed with HTTP status {resp.status}")
            data = await resp.json()
    except Exception as e:
        raise CommandError(f"DoH resolution failed: {e}")

    status = data.get("Status", -1)
    if status != 0:
        status_meanings = {2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}
        err_status = status_meanings.get(status, f"Status code {status}")
        raise CommandError(f"DNS lookup error: {err_status}")

    answers = data.get("Answer", [])
    if not answers:
        await event.edit(render(
            title=f"DNS // {domain}",
            rows=[f"Query Type: {record_type}", "Status: NOERROR (No records found)"],
            footer="network_osint | dns"
        ))
        return

    rows = [f"Domain: {domain}", f"Type: {record_type}", "---"]
    for ans in answers:
        data_val = ans.get("data", "")
        ttl = ans.get("TTL", "")
        rows.append(f"• {data_val} (TTL: {ttl}s)")

    await event.edit(render(
        title="DNS LOOKUP",
        rows=rows,
        footer="network_osint | dns"
    ))
