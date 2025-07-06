import socket
from domain.models import Finding, FindingType

def scan_ports(url: str):
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
