import json
from pathlib import Path
from datetime import datetime

def generate(url: str, findings: list):
    safe_url = url.replace("http://", "").replace("https://", "").replace("/", "_")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{safe_url}_{timestamp}.json"
    path = Path("reports") / filename
    path.parent.mkdir(exist_ok=True)
    with open(path, "w") as f:
        json.dump({"url": url, "findings": findings}, f, indent=2)
