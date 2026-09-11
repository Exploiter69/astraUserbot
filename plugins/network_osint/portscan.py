import re
import asyncio
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}portscan(?:\s+(\S+))?(?:\s+(.*))?$"

COMMON_PORTS = {
    21: "FTP", 22: "SSH", 25: "SMTP", 53: "DNS", 80: "HTTP", 110: "POP3",
    143: "IMAP", 443: "HTTPS", 465: "SMTPS", 587: "Submission", 993: "IMAPS",
    995: "POP3S", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 8080: "HTTP-Proxy", 8443: "HTTPS-Alt"
}
_MAX_PORTS = 50
_MAX_HOST = 253

async def setup(client):
    register_cmd(client, pattern=PATTERN, handler=handle_portscan, category="network_osint", description="Scan common TCP ports on a host. Usage: .portscan <host> [port1,port2...]")

async def _check_port(host: str, port: int, timeout: float = 1.5) -> tuple[int, bool]:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return port, True
    except Exception:
        return port, False

async def handle_portscan(event):
    host = (event.pattern_match.group(1) or "").strip()
    custom_ports_raw = (event.pattern_match.group(2) or "").strip()
    if not host:
        raise CommandError("Please provide a target host. Usage: .portscan <host> [ports]")
    if len(host) > _MAX_HOST or any(ch.isspace() for ch in host):
        raise CommandError("Target host is invalid or too long.")

    if custom_ports_raw:
        ports_to_scan = []
        for raw in custom_ports_raw.replace(" ", ",").split(","):
            raw = raw.strip()
            if not raw:
                continue
            if not raw.isdigit():
                raise CommandError("Custom ports must be a comma-separated list of integers.")
            port = int(raw)
            if not 1 <= port <= 65535:
                raise CommandError("Ports must be between 1 and 65535.")
            if port not in ports_to_scan:
                ports_to_scan.append(port)
    else:
        ports_to_scan = list(COMMON_PORTS.keys())

    if not ports_to_scan:
        raise CommandError("Please provide at least one valid port.")
    if len(ports_to_scan) > _MAX_PORTS:
        raise CommandError(f"Maximum limit is {_MAX_PORTS} unique ports per scan.")

    await event.edit(render(title="PORT SCANNER", rows=[f"Scanning {host}...", f"Ports: {len(ports_to_scan)} targets"], footer="network_osint | portscan"))
    results = await asyncio.gather(*[_check_port(host, port) for port in ports_to_scan])
    open_ports = [port for port, is_open in results if is_open]
    rows = [f"Target: {host}", f"Scanned: {len(ports_to_scan)} ports", "---"]
    if open_ports:
        rows.append("OPEN PORTS:")
        rows.extend(f"  [{port}/tcp] → {COMMON_PORTS.get(port, 'Unknown')}" for port in sorted(open_ports))
    else:
        rows.append("No open ports found within timeout window.")
    await event.edit(render(title="SCAN RESULTS", rows=rows, footer="network_osint | portscan"))
