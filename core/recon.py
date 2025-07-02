import requests

def run(url: str):
    try:
        response = requests.get(url, timeout=10)
        return [{
            "type": "info",
            "status_code": response.status_code,
            "headers": dict(response.headers),
        }]
    except Exception as e:
        return [{"type": "error", "message": str(e)}]
