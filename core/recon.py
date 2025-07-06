from domain.models import Finding, FindingType
import requests

def run(url: str):
    try:
        response = requests.get(url, timeout=10)
        return [
            Finding(
                type=FindingType.INFO,
                detail=f"Status code: {response.status_code}",
                extra={"headers": dict(response.headers)}
            )
        ]
    except Exception as e:
        return [
            Finding(
                type=FindingType.ERROR,
                detail=str(e)
            )
        ]