import requests

from domain.models import Finding, FindingType
from gpt import client, prompts
from core import settings

_SQL_ERROR_SIGNS = (
    "sql", "syntax", "mysql", "psql", "postgre", "sqlite",
    "odbc", "ora-", "warning: mysql", "unclosed quotation",
)


def test(url: str):
    """
    Test for SQL Injection on a target URL using LLM-generated payloads
    (with a static fallback from config.yaml). Flags responses containing
    typical SQL error indicators.

    Returns:
        list[Finding]: SQLi or error findings.
    """
    payloads = client.generate_payloads(prompts.sqli_prompt(url))
    if not payloads:
        payloads = settings.load().get("sqli_payloads", [])

    timeout = settings.request_timeout()
    findings = []

    for payload in payloads:
        target = f"{url}?user={payload}&pass=test"
        try:
            r = requests.get(target, timeout=timeout)
            body = r.text.lower()
            if any(sign in body for sign in _SQL_ERROR_SIGNS):
                findings.append(
                    Finding(
                        type=FindingType.SQLI,
                        detail="Posible SQLi: la respuesta contiene indicadores de error SQL",
                        url=target,
                        payload=payload,
                    )
                )
        except Exception as e:
            findings.append(
                Finding(
                    type=FindingType.ERROR,
                    detail=f"Error al probar SQLi: {e}",
                    url=target,
                    payload=payload,
                )
            )

    return findings
