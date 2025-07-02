import requests
from gpt import client, prompts

def test(url: str):
    prompt = prompts.sqli_prompt(url)
    payloads = client.generate_payloads(prompt)
    results = []
    for payload in payloads:
        try:
            r = requests.get(f"{url}?user={payload}&pass=test", timeout=10)
            if "sql" in r.text.lower() or "syntax" in r.text.lower():
                results.append({"type": "sqli", "payload": payload})
        except:
            continue
    return results
