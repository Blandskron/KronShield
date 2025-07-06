from core import recon, scanner, xss, sqli
from domain.models import Finding
from typing import List

def audit_website(url: str) -> List[Finding]:
    findings: List[Finding] = []
    findings += recon.run(url)
    findings += scanner.scan_ports(url)
    findings += xss.test(url)
    findings += sqli.test(url)
    return findings