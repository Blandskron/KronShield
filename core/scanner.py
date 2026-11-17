import socket
from urllib.parse import urlparse

from application.transport import SafeTransport
from domain.authorization import Address, ScopeTarget
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
            findings.append(_open_port(port))
            sock.close()
        except OSError:
            continue

    return findings


def scan_authorized_port(target: ScopeTarget, transport: SafeTransport) -> Finding:
    """Probe exactly the port subject to the transport's scope decision."""
    if target.port is None:
        raise ValueError("TCP probe requires an effective port")
    return _open_port(target.port, transport.tcp(target))


def _open_port(port: int, peer: Address | None = None) -> Finding:
    extra = {"port": port, "status": "open"}
    if peer is not None:
        extra["peer"] = str(peer)
    return Finding(type=FindingType.PORT, detail=f"Puerto {port} abierto", extra=extra)
