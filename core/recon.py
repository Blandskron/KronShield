from domain.models import Finding, FindingType
import requests

def run(url: str):
    """
    Performs a passive reconnaissance request to the target URL.

    Retrieves the HTTP status code and response headers.
    In case of failure, returns an error finding.

    Args:
        url (str): Target URL to be analyzed.

    Returns:
        list[Finding]: A list containing either an info-level finding or an error.
    """
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