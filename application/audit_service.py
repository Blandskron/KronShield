from domain.models import Finding
from core.recon import run as info_check
from core.scanner import scan_ports
from core.xss import test as test_xss
from core.sqli import test as test_sqli
from reports.generator import generate_pdf_report_from_json
from infra.db import SessionLocal
from infra.repository import save_findings

def audit_website(url: str, api_key: str) -> list[Finding]:
    findings: list[Finding] = []

    # Ejecutar todos los módulos
    findings.extend(info_check(url))
    findings.extend(scan_ports(url))
    findings.extend(test_xss(url))
    findings.extend(test_sqli(url))

    # Guardar hallazgos en la base de datos
    with SessionLocal() as db:
        save_findings(db, findings, url)

    # También generar el PDF (puede usarse el path en otra parte)
    serializable = [f.__dict__ for f in findings]
    generate_pdf_report_from_json(url, serializable, api_key)

    return findings
