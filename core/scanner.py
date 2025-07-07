import socket
from domain.models import Finding, FindingType

def scan_ports(url: str):
    """
    Performs a basic TCP port scan on common HTTP/HTTPS ports.

    Attempts to connect to ports 80, 443, 8080, and 8443 on the target host.
    Returns a list of open ports as findings.

    Args:
        url (str): Target URL to extract the host from.

    Returns:
        list[Finding]: A list of findings for each open port detected.
    """
    host = url.replace("http://", "").replace("https://", "").split("/")[0]
    findings = []

    for port in [80, 443, 8080, 8443]:
        try:
            sock = socket.create_connection((host, port), timeout=2)
            findings.append(
                Finding(
                    type=FindingType.PORT,
                    detail=f"Puerto {port} abierto",
                    extra={"port": port, "status": "open"}
                )
            )
            sock.close()
        except:
            continue

    return findings
