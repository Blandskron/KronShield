import json
from unittest.mock import Mock

import dotenv
import pytest
from typer.testing import CliRunner


@pytest.fixture
def invoke(monkeypatch):
    monkeypatch.setattr(dotenv, "load_dotenv", Mock())
    from main import app

    return lambda *args: CliRunner().invoke(app, ["audit", *args])


def test_active_cli_command_fails_closed_without_echoing_the_target(invoke, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = invoke("run", "-u", "http://127.0.0.1/?token=secret")

    assert result.exit_code == 4
    assert "deshabilitada" in result.stderr
    assert "secret" not in result.output
    assert not list(tmp_path.iterdir())


def test_cli_plan_previews_an_unverified_target_without_network(invoke):
    result = invoke("plan", "-u", "https://scope.example/api/", "--environment", "lab")

    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["profile"] == "web-baseline"
    assert plan["technique"] == "http-baseline"
    assert plan["target"]["host"] == "scope.example"
    assert plan["target"]["path"] == ["api"]
    assert plan["target"]["trailing_slash"]
    assert plan["scope"] == "missing_authorization"
    assert plan["execution"] == "disabled"
    assert plan["limits"]["max_operations"] > 0


def test_cli_plan_rejects_invalid_authority_without_reprinting_credentials(invoke):
    result = invoke("plan", "-u", "https://operator:secret@scope.example/")

    assert result.exit_code == 2
    assert "Plan inválido" in result.stderr
    assert "secret" not in result.output


def test_tcp_preview_requires_a_port_target_without_application_path(invoke):
    result = invoke("plan", "-u", "https://scope.example:8443", "--profile", "tcp-baseline")
    assert result.exit_code == 0, result.output
    planned = json.loads(result.stdout)
    assert planned["technique"] == "tcp-connect"
    assert planned["target"]["port"] == 8443
    assert planned["target"]["scheme"] is None
    invalid = invoke("plan", "-u", "https://scope.example:8443/admin", "--profile", "tcp-baseline")
    assert invalid.exit_code == 2


@pytest.mark.parametrize(
    ("check", "body", "options", "expected"),
    [
        ("xss", "echo test-marker", ["--marker", "test-marker"], True),
        ("xss", "clean body", ["--marker", "test-marker"], False),
        ("sqli", "SQLite error", [], True),
        ("sqli", "clean body", [], False),
    ],
)
def test_cli_analyzes_saved_http_body_offline(invoke, tmp_path, check, body, options, expected):
    artifact = tmp_path / "captured-body.txt"
    artifact.write_text(body, encoding="utf8")
    result = invoke("analyze", "-i", str(artifact), "--check", check, *options)

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["check"] == check
    if expected:
        finding, = data["findings"]
        assert finding["type"] == check
        assert finding["detail"].startswith("Posible")
        assert finding["payload"] is None
    else:
        assert data["findings"] == []


@pytest.mark.parametrize("body", [b"\xff", b"x" * (256 * 1024 + 1)], ids=["invalid-utf8", "too-large"])
def test_cli_rejects_invalid_capture(invoke, tmp_path, body):
    artifact = tmp_path / "captured-body.txt"
    artifact.write_bytes(body)
    result = invoke("analyze", "-i", str(artifact), "--check", "sqli")
    assert result.exit_code == 2


@pytest.mark.parametrize("options", [[], ["--marker", " "], ["--marker", "x" * 4097]], ids=[
    "missing-marker", "blank-marker", "too-long-marker",
])
def test_cli_rejects_invalid_xss_marker(invoke, tmp_path, options):
    artifact = tmp_path / "captured-body.txt"
    artifact.write_text("fixture", encoding="utf8")
    result = invoke("analyze", "-i", str(artifact), "--check", "xss", *options)
    assert result.exit_code == 2
