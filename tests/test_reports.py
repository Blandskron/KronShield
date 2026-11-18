import json
from unittest.mock import Mock

import httpx
from groq import Groq

from gpt import client
from reports.report_html import generate_html_report


def test_groq_summary_client_uses_mock_transport(monkeypatch):
    response = httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": "  Resumen simulado  "}}],
    })
    reply = Mock(return_value=response)
    messages = [{"role": "user", "content": "fixture prompt"}]

    with httpx.Client(transport=httpx.MockTransport(reply)) as transport:
        monkeypatch.setattr(client, "_client", Groq(
            api_key="fixture-key",
            base_url="https://fixture.invalid",
            http_client=transport,
            max_retries=0,
        ))
        assert client.chat(messages, max_tokens=512) == "Resumen simulado"

    reply.assert_called_once()
    request = reply.call_args.args[0]
    assert request.method == "POST"
    assert request.url.path == "/openai/v1/chat/completions"
    body = json.loads(request.content)
    assert body["messages"] == messages


def test_html_report_renders_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    md = "## Resumen Ejecutivo\nTexto intro\n\n## Hallazgos\n### Uno\n- item **a**\n- item b"
    out = generate_html_report(md, "example.com")
    html = open(out, encoding="utf-8").read()
    assert "<h2>Resumen Ejecutivo</h2>" in html
    assert "<h3>Uno</h3>" in html
    assert "<li>item <strong>a</strong></li>" in html
