import socket
from urllib.parse import urlparse

from domain.models import Finding, FindingType
from core import settings


def scan_ports(url: str):
    """
    Perform a basic TCP port scan on the configured HTTP/HTTPS ports.

    Args:
        url: target URL to extract the host from.

    Returns:
        list[Finding]: one finding per open port detected.
    """
    host = urlparse(url).netloc.split("@")[-1].split(":")[0]
    findings = []

    for port in settings.ports_to_scan():
        try:
            sock = socket.create_connection((host, port), timeout=2)
            findings.append(
                Finding(
                    type=FindingType.PORT,
                    detail=f"Puerto {port} abierto",
                    extra={"port": port, "status": "open"},
                )
            )
            sock.close()
        except OSError:
            continue

    return findings
