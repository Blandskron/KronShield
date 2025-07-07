import json
from pathlib import Path
from datetime import datetime

def generate(url: str, findings: list):
    """
    Saves audit findings to a timestamped JSON file.

    The output filename is derived from the target URL and current UTC timestamp.
    The resulting file is stored in the 'reports' directory.

    Args:
        url (str): Audited target URL.
        findings (list): List of serialized findings (dictionaries).
    """
    safe_url = url.replace("http://", "").replace("https://", "").replace("/", "_")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{safe_url}_{timestamp}.json"
    path = Path("reports") / filename
    path.parent.mkdir(exist_ok=True)
    with open(path, "w") as f:
        json.dump({"url": url, "findings": findings}, f, indent=2)
