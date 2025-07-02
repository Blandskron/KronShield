import requests
from gpt import client, prompts

def test(url: str):
    prompt = prompts.xss_prompt(url)
    payloads = client.generate_payloads(prompt)
    results = []
    for payload in payloads:
        target = f"{url}?q={payload}"
        try:
            r = requests.get(target, timeout=10)
            if payload in r.text:
                results.append({"type": "xss", "payload": payload, "url": target})
        except:
            continue
    return results
