import requests

from domain.models import Finding, FindingType
from core import settings

# Common security headers whose absence is worth reporting.
_SECURITY_HEADERS = [
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
]


def run(url: str):
    """
    Passive reconnaissance: fetch the target, record status/headers, and flag
    missing common security headers.

    Args:
        url: target URL to analyze.

    Returns:
        list[Finding]: an info finding plus any missing-header findings, or an
        error finding if the request fails.
    """
    try:
        response = requests.get(url, timeout=settings.request_timeout())
    except Exception as e:
        return [Finding(type=FindingType.ERROR, detail=str(e), url=url)]

    findings = [
        Finding(
            type=FindingType.INFO,
            detail=f"Status code: {response.status_code}",
            url=url,
            extra={
                "server": response.headers.get("Server"),
                "headers": dict(response.headers),
            },
        )
    ]

    present = {h.lower() for h in response.headers}
    missing = [h for h in _SECURITY_HEADERS if h.lower() not in present]
    if missing:
        findings.append(
            Finding(
                type=FindingType.INFO,
                detail="Cabeceras de seguridad ausentes: " + ", ".join(missing),
                url=url,
                extra={"missing_security_headers": missing},
            )
        )

    return findings
