from domain.models import Finding
from core.recon import run as info_check
from core.scanner import scan_ports
from core.xss import test as test_xss
from core.sqli import test as test_sqli


def audit_website(url: str, api_key: str | None = None) -> list[Finding]:
    """
    Run the full security-audit pipeline against a target URL:
      - Passive information gathering (recon)
      - Port scanning
      - Reflected XSS testing
      - SQL Injection testing

    Persistence (database + JSON export) is handled by the caller (cli.audit),
    so this function only orchestrates the checks and returns the findings.

    Args:
        url: target website URL to audit.
        api_key: Groq API key (the LLM client is initialized by the caller).

    Returns:
        list[Finding]: all findings produced by the audit stages.
    """
    findings: list[Finding] = []
    findings.extend(info_check(url))
    findings.extend(scan_ports(url))
    findings.extend(test_xss(url))
    findings.extend(test_sqli(url))
    return findings
