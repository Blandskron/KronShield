import json
from unittest.mock import Mock

import httpx
from groq import Groq

from gpt import client
from reports.report_html import generate_html_report


def test_clean_payloads_strips_markers_and_fences():
    raw = "```\n1. <script>alert(1)</script>\n- ' OR '1'='1\n\n`plain`\n```"
    cleaned = client._clean_payloads(raw)
    assert "<script>alert(1)</script>" in cleaned
    assert "' OR '1'='1" in cleaned
    assert "plain" in cleaned
    assert all(not p.startswith("```") for p in cleaned)


def test_groq_payloads_use_mock_transport(monkeypatch):
    response = httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": "1. fixture-marker"}}],
    })
    reply = Mock(return_value=response)

    with httpx.Client(transport=httpx.MockTransport(reply)) as transport:
        monkeypatch.setattr(client, "_client", Groq(
            api_key="fixture-key",
            base_url="https://fixture.invalid",
            http_client=transport,
            max_retries=0,
        ))
        assert client.generate_payloads("fixture prompt") == ["fixture-marker"]

    reply.assert_called_once()
    request = reply.call_args.args[0]
    assert request.method == "POST"
    assert request.url.path == "/openai/v1/chat/completions"
    body = json.loads(request.content)
    assert body["messages"][-1] == {"role": "user", "content": "fixture prompt"}


def test_html_report_renders_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    md = "## Resumen Ejecutivo\nTexto intro\n\n## Hallazgos\n### Uno\n- item **a**\n- item b"
    out = generate_html_report(md, "example.com")
    html = open(out, encoding="utf-8").read()
    assert "<h2>Resumen Ejecutivo</h2>" in html
    assert "<h3>Uno</h3>" in html
    assert "<li>item <strong>a</strong></li>" in html
