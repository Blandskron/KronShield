import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from groq import Groq

from application.report_input import SavedAudit
from core import report
from gpt import client
from infra import artifacts
from reports.report_html import generate_audit_html_report, generate_html_report


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


def test_report_escapes_markup_in_every_dynamic_html_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hostile = '</title><script>x</script><img src=x onerror=x>&"\''
    audit = SavedAudit.model_validate_json(json.dumps({
        "url": hostile,
        "findings": [{
            "type": hostile, "detail": hostile, "url": hostile, "payload": hostile,
            "extra": {"missing_security_headers": [hostile]},
        }],
    }))

    output = Path(generate_audit_html_report(audit, f"### {hostile}\n- **{hostile}**"))
    html = output.read_text(encoding="utf8")
    assert output.resolve().parent == tmp_path / "results"
    assert re.fullmatch(r"report-[0-9a-f]{32}\.html", output.name)
    assert f"<title>Informe de Auditoría - {escape(hostile)}</title>" in html
    assert html.count(escape(hostile)) == 9
    assert "default-src 'none'" in html

    class Markup(HTMLParser):
        def handle_starttag(self, tag, attrs):
            assert tag not in {"script", "img", "iframe", "a", "link", "base"}
            assert not any(name.startswith("on") for name, _ in attrs)

    Markup().feed(html)


@pytest.mark.parametrize("label", ["../../outside", "..\\..\\outside", "C:\\outside\\CON", "/etc/report", "NUL"])
def test_html_and_json_names_do_not_depend_on_untrusted_url_or_label(tmp_path, monkeypatch, label):
    monkeypatch.chdir(tmp_path)
    html = Path(generate_html_report("## Informe", label))
    snapshot = Path(report.generate(label, []))

    assert html.resolve().parent == snapshot.resolve().parent == tmp_path / "results"
    assert re.fullmatch(r"report-[0-9a-f]{32}\.html", html.name)
    assert re.fullmatch(r"report-[0-9a-f]{32}\.json", snapshot.name)
    assert json.loads(snapshot.read_text(encoding="utf8"))["url"] == label


def test_repeated_and_concurrent_reports_have_deterministic_contents_and_distinct_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    audit = SavedAudit(url="https://scope.example", findings=())

    with ThreadPoolExecutor(max_workers=4) as workers:
        paths = list(workers.map(lambda _: Path(generate_audit_html_report(audit)), range(8)))

    assert len(set(paths)) == 8
    assert len({path.read_bytes() for path in paths}) == 1
    assert set(Path("results").iterdir()) == set(paths)


def test_publication_retries_collisions_and_exposes_only_complete_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = Path("results")
    directory.mkdir()
    collision, available = UUID(int=1), UUID(int=2)
    existing = directory / f"report-{collision.hex}.html"
    existing.write_text("prior report", encoding="utf8")
    monkeypatch.setattr(artifacts, "uuid4", Mock(side_effect=[collision, available]))
    link = os.link

    def observe(source, destination):
        assert source.read_text(encoding="utf8").rstrip().endswith("</html>")
        link(source, destination)

    monkeypatch.setattr(artifacts.os, "link", observe)
    path = Path(generate_html_report("Cuerpo", "example.com"))

    assert path == directory / f"report-{available.hex}.html"
    assert existing.read_text(encoding="utf8") == "prior report"
    assert set(directory.iterdir()) == {existing, path}


def test_failed_atomic_publication_leaves_no_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(artifacts.os, "link", Mock(side_effect=OSError("fixture write error")))
    with pytest.raises(OSError):
        generate_html_report("Report", "example.com")
    assert list(Path("results").iterdir()) == []


def test_results_directory_symlink_cannot_route_reports_outside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (workspace / "results").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable for this test user")
    monkeypatch.chdir(workspace)

    with pytest.raises(ValueError, match="results directory"):
        generate_html_report("Report", "example.com")
    assert list(outside.iterdir()) == []
