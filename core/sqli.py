import requests
from domain.models import Finding, FindingType
from gpt import client, prompts

def test(url: str):
    """
    Tests for potential SQL Injection vulnerabilities on a given URL.

    Uses GPT-generated payloads to attempt injection via query parameters.
    Flags responses that contain typical SQL error indicators.

    Args:
        url (str): The target URL to test.

    Returns:
        list[Finding]: A list of SQLI or error findings.
    """
    prompt = prompts.sqli_prompt(url)
    payloads = client.generate_payloads(prompt)
    findings = []

    for payload in payloads:
        try:
            r = requests.get(f"{url}?user={payload}&pass=test", timeout=10)
            if "sql" in r.text.lower() or "syntax" in r.text.lower():
                findings.append(
                    Finding(
                        type=FindingType.SQLI,
                        detail="SQLi detectado con payload",
                        url=f"{url}?user={payload}&pass=test",
                        payload=payload
                    )
                )
        except Exception as e:
            findings.append(
                Finding(
                    type=FindingType.ERROR,
                    detail=f"Error al probar SQLi con {payload}: {e}",
                    url=url,
                    payload=payload
                )
            )

    return findings
