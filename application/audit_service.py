from domain.models import Finding
from core.recon import run as info_check
from core.scanner import scan_ports
from core.xss import test as test_xss
from core.sqli import test as test_sqli
from reports.generator import generate_pdf_report_from_json
from infra.db import SessionLocal
from infra.repository import save_findings

def audit_website(url: str, api_key: str) -> list[Finding]:
    """
    Executes a full security audit pipeline against a target URL, including:
    - Passive information gathering
    - Port scanning
    - XSS vulnerability testing
    - SQL Injection testing

    Results are persisted to the database and a PDF report is generated.

    Args:
        url (str): Target website URL to be audited.
        api_key (str): API key used for external integrations (e.g., report generation with OpenAI).

    Returns:
        list[Finding]: A list of all findings discovered during the audit process.
    """
    findings: list[Finding] = []

    findings.extend(info_check(url))
    findings.extend(scan_ports(url))
    findings.extend(test_xss(url))
    findings.extend(test_sqli(url))

    with SessionLocal() as db:
        save_findings(db, findings, url)

    serializable = [f.__dict__ for f in findings]
    generate_pdf_report_from_json(url, serializable, api_key)

    return findings
