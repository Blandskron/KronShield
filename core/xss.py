import requests
from domain.models import Finding, FindingType
from gpt import client, prompts

def test(url: str):
    prompt = prompts.xss_prompt(url)
    payloads = client.generate_payloads(prompt)
    findings = []

    for payload in payloads:
        target = f"{url}?q={payload}"
        try:
            r = requests.get(target, timeout=10)
            if payload in r.text:
                findings.append(
                    Finding(
                        type=FindingType.XSS,
                        detail="XSS detectado con payload",
                        url=target,
                        payload=payload
                    )
                )
        except Exception as e:
            findings.append(
                Finding(
                    type=FindingType.ERROR,
                    detail=f"Error al probar XSS con {payload}: {e}",
                    url=target,
                    payload=payload
                )
            )

    return findings
