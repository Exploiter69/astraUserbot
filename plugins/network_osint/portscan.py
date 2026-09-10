import re
import asyncio
from core.registry import register_cmd
from core.errors import CommandError
from helpers.hud import render
from config import config

PATTERN = rf"^{re.escape(config.PREFIX)}portscan(?:\s+(\S+))?(?:\s+(.*))?$"

COMMON_PORTS = {
    21: "FTP",
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    143: "IMAP",
    443: "HTTPS",
    465: "SMTPS",
    587: "Submission",
    993: "IMAPS",
    995: "POP3S",
    3306: "MySQL",
    3389: "RDP",
    5432: "PostgreSQL",
    8080: "HTTP-Proxy",
    8443: "HTTPS-Alt"
}

async def setup(client):
    register_cmd(
        client,
        pattern=PATTERN,
        handler=handle_portscan,
        category="network_osint",
        description="Scan common TCP ports on a host. Usage: .portscan <host> [port1,port2...]"
    )

async def _check_port(host: str, port: int, timeout: float = 1.5) -> tuple[int, bool]:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return port, True
    except Exception:
        return port, False

async def handle_portscan(event):
    host = event.pattern_match.group(1)
    custom_ports_raw = event.pattern_match.group(2)
    
    if not host:
        raise CommandError("Please provide a target host. Usage: .portscan <host> [ports]")

    ports_to_scan = []
    if custom_ports_raw:
        try:
            for p in custom_ports_raw.replace(" ", ",").split(","):
                if p.strip():
                    ports_to_scan.append(int(p.strip()))
        except ValueError:
            raise CommandError("Custom ports must be a comma-separated list of integers.")
    else:
        ports_to_scan = list(COMMON_PORTS.keys())

    if len(ports_to_scan) > 50:
        raise CommandError("Maximum limit is 50 ports per scan.")

    await event.edit(render(
        title="PORT SCANNER",
        rows=[f"Scanning {host}...", f"Ports: {len(ports_to_scan)} targets"],
        footer="network_osint | portscan"
    ))

    tasks = [_check_port(host, port) for port in ports_to_scan]
    results = await asyncio.gather(*tasks)

    open_ports = [p for p, is_open in results if is_open]

    rows = [f"Target: {host}", f"Scanned: {len(ports_to_scan)} ports", "---"]
    if open_ports:
        rows.append("OPEN PORTS:")
        for p in sorted(open_ports):
            svc = COMMON_PORTS.get(p, "Unknown")
            rows.append(f"  [{p}/tcp] → {svc}")
    else:
        rows.append("No open ports found within timeout window.")

    await event.edit(render(
        title="SCAN RESULTS",
        rows=rows,
        footer="network_osint | portscan"
    ))
