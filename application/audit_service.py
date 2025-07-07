from domain.models import Finding
from core.recon import run as info_check
from core.scanner import scan_ports
from core.xss import test as test_xss
from core.sqli import test as test_sqli
from infra.db import SessionLocal
from infra.repository import save_findings
from urllib.parse import urlparse
from pathlib import Path
import json

def audit_website(url: str, api_key: str) -> list[Finding]:
    """
    Executes a full security audit pipeline against a target URL, including:
    - Passive information gathering
    - Port scanning
    - XSS vulnerability testing
    - SQL Injection testing

    The results are saved to the database and exported as a JSON file
    under the results/{domain}/{domain}.json path.

    Args:
        url (str): Target website URL to audit.
        api_key (str): API key for integrations (e.g., GPT).

    Returns:
        list[Finding]: List of findings from the audit.
    """
    findings: list[Finding] = []

    findings.extend(info_check(url))
    findings.extend(scan_ports(url))
    findings.extend(test_xss(url))
    findings.extend(test_sqli(url))

    with SessionLocal() as db:
        save_findings(db, findings, url)

    # Save findings as JSON in results/{domain}/{domain}.json
    domain = urlparse(url).netloc.replace("www.", "")
    results_dir = Path("results") / domain
    results_dir.mkdir(parents=True, exist_ok=True)

    output_file = results_dir / f"{domain}.json"
    serializable = [f.__dict__ for f in findings]

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"url": url, "findings": serializable}, f, indent=2, ensure_ascii=False)

    return findings
