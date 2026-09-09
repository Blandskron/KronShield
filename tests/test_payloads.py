from gpt.client import _clean_payloads
from reports.report_html import generate_html_report


def test_clean_payloads_strips_markers_and_fences():
    raw = "```\n1. <script>alert(1)</script>\n- ' OR '1'='1\n\n`plain`\n```"
    cleaned = _clean_payloads(raw)
    assert "<script>alert(1)</script>" in cleaned
    assert "' OR '1'='1" in cleaned
    assert "plain" in cleaned
    assert all(not p.startswith("```") for p in cleaned)


def test_html_report_renders_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    md = "## Resumen Ejecutivo\nTexto intro\n\n## Hallazgos\n### Uno\n- item **a**\n- item b"
    out = generate_html_report(md, "example.com")
    html = open(out, encoding="utf-8").read()
    assert "<h2>Resumen Ejecutivo</h2>" in html
    assert "<h3>Uno</h3>" in html
    assert "<li>item <strong>a</strong></li>" in html
