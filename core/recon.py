import requests

from application.transport import SafeTransport
from domain.authorization import ScopeTarget
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

    return _observations(url, response.status_code, dict(response.headers))


def run_authorized(target: ScopeTarget, transport: SafeTransport) -> list[Finding]:
    """Collect selective HTTP metadata through the scope-gated transport."""
    response = transport.http(target)
    recorded_headers = {"server", *(header.lower() for header in _SECURITY_HEADERS)}
    headers = {
        name: value for name, value in response.headers if name.lower() in recorded_headers
    }
    return _observations(response.url, response.status, headers)


def _observations(url: str, status: int, headers: dict[str, str]) -> list[Finding]:
    present = {name.lower(): value for name, value in headers.items()}
    findings = [
        Finding(
            type=FindingType.INFO,
            detail=f"Status code: {status}",
            url=url,
            extra={
                "server": present.get("server"),
                "headers": headers,
            },
        )
    ]

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
