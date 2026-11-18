import json
from pathlib import Path
from unittest.mock import Mock

import dotenv
import pytest
from typer.testing import CliRunner

from gpt import client, summarize


@pytest.fixture
def report_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dotenv, "load_dotenv", Mock())
    from main import app

    return lambda *args: CliRunner().invoke(app, ["report", "generate", *args])


def test_generate_renders_legacy_json_locally_by_default(report_cli, monkeypatch):
    init = Mock(side_effect=AssertionError("Unexpected provider call"))
    monkeypatch.setattr(client, "init", init)
    audit = {
        "url": "https://scope.example:8443/a?x=1&y=2",
        "findings": [
            {
                "type": "info", "detail": "Servidor en español", "url": None,
                "payload": None, "extra": {"missing_security_headers": ["X-Frame-Options"]},
            },
            {"type": "port", "detail": "Puerto 443 abierto", "extra": {"port": 443}},
        ],
    }
    Path("capture.json").write_text(json.dumps(audit), encoding="utf8")

    result = report_cli("--input", "capture.json")

    assert result.exit_code == 0, result.output
    output, = Path("results").glob("*.html")
    rendered = output.read_text(encoding="utf8")
    assert "x=1&amp;y=2" in rendered
    assert "Servidor en español" in rendered
    assert "Cabeceras ausentes: X-Frame-Options" in rendered
    assert "Resumen asistido" not in rendered
    init.assert_not_called()


@pytest.mark.parametrize("payload", [
    b"{",
    b'{"url":"https://scope.example","findings":{}}',
    b'{"url":"https://scope.example","findings":[{"type":"info","detail":null}]}',
    json.dumps({"url": "https://scope.example", "findings": [{"type": "info", "detail": ""}] * 1001}).encode(),
    b"x" * (1024 * 1024 + 1),
], ids=["syntax", "type", "finding", "count", "size"])
def test_invalid_report_json_fails_before_writing_or_contacting_ai(report_cli, monkeypatch, payload):
    Path("capture.json").write_bytes(payload)
    init = Mock(side_effect=AssertionError("Unexpected provider call"))
    monkeypatch.setattr(client, "init", init)

    result = report_cli("-i", "capture.json", "--with-ai")

    assert result.exit_code == 2
    assert "Entrada inválida" in result.stderr
    assert not Path("results").exists()
    init.assert_not_called()


def test_opt_in_groq_receives_only_type_and_detail_and_output_is_escaped(report_cli, monkeypatch):
    audit = {
        "url": "https://scope.example/?token=fixture-secret",
        "findings": [{"type": "info", "detail": "Texto para resumen", "payload": "fixture-payload"}],
    }
    Path("capture.json").write_text(json.dumps(audit), encoding="utf8")
    init = Mock()
    summarize_report = Mock(return_value="## Resumen\n<script>alert(1)</script>")
    monkeypatch.setattr(client, "init", init)
    monkeypatch.setattr(summarize, "generate_summary", summarize_report)

    result = report_cli("-i", "capture.json", "--with-ai")

    assert result.exit_code == 0, result.output
    init.assert_called_once_with()
    summarize_report.assert_called_once_with({"findings": [{"type": "info", "detail": "Texto para resumen"}]})
    output, = Path("results").glob("*.html")
    report = output.read_text(encoding="utf8")
    assert "Resumen asistido por IA" in report
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in report
    assert "<script>" not in report
