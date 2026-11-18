"""Write a JSON snapshot of audit findings."""

import json

from infra.artifacts import publish_report


def generate(url: str, findings: list) -> str:
    content = json.dumps({"url": url, "findings": findings}, indent=2, ensure_ascii=False)
    return str(publish_report(content, "json"))
