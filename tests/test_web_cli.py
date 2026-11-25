import json
import shlex
from contextlib import contextmanager
from uuid import uuid4

import httpx
from typer.testing import CliRunner

from cli import web
from main import app


def test_copy_command_quotes_shell_metacharacters():
    arguments = ["pentest-agent", "plan", "show", "José's workspace @$", "a;b&c"]
    assert shlex.split(web.shell_command(arguments, "bash")) == arguments
    assert web.shell_command(arguments, "powershell") == (
        "& 'pentest-agent' 'plan' 'show' 'José''s workspace @$' 'a;b&c'"
    )


def test_cli_plan_calls_shared_route_and_returns_browser_link(monkeypatch):
    org, project, assessment, authorization, target, plan = map(str, (uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()))
    monkeypatch.setenv("PENTEST_AGENT_API_URL", "https://app.example")
    monkeypatch.delenv("PENTEST_AGENT_BROWSER_ORIGIN", raising=False)

    def send(request):
        assert request.method == "POST" and request.url.path == f"/api/v1/projects/{project}/plans"
        assert request.url.params["org_id"] == org
        assert request.headers["Idempotency-Key"] == "plan-replay-example"
        assert json.loads(request.content) == {
            "assessment_id": assessment, "authorization_id": authorization, "authorization_revision": 1,
            "target_ids": [target], "profile_id": "scope-review",
        }
        return httpx.Response(201, json={"id": plan, "status": "reviewed"})

    @contextmanager
    def local_client():
        with httpx.Client(base_url="https://app.example", transport=httpx.MockTransport(send)) as http:
            yield http

    monkeypatch.setattr(web, "client", local_client)
    result = CliRunner().invoke(app, ["plan", "create", "--org-id", org, "--project-id", project,
        "--assessment-id", assessment, "--authorization-id", authorization, "--revision", "1",
        "--target-id", target, "--idempotency-key", "plan-replay-example"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["id"] == plan
    assert shlex.split(payload["commands"]["bash"])[-2:] == ["--plan-id", plan]
    assert payload["commands"]["powershell"].endswith("'--plan-id' '" + plan + "'")
    assert payload["browser_url"] == f"https://app.example/#plan?org={org}&project={project}&id={plan}"


def test_cli_report_emits_html_bytes_from_shared_api(monkeypatch):
    org, project, plan = (str(uuid4()) for _ in range(3))
    html = "<!DOCTYPE html><p>Revisión guardada</p>".encode()

    def send(request):
        assert request.url.path == f"/api/v1/projects/{project}/plans/{plan}/report"
        assert request.url.params["org_id"] == org
        return httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, content=html)

    @contextmanager
    def local_client():
        with httpx.Client(base_url="https://app.example", transport=httpx.MockTransport(send)) as http:
            yield http

    monkeypatch.setattr(web, "client", local_client)
    result = CliRunner().invoke(app, ["plan", "report", "--org-id", org, "--project-id", project, "--plan-id", plan])
    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == html


def test_cli_reads_and_updates_shared_team_selection(monkeypatch):
    org, project = str(uuid4()), str(uuid4())
    monkeypatch.setenv("PENTEST_AGENT_API_URL", "https://app.example")
    monkeypatch.setenv("PENTEST_AGENT_API_TOKEN", "fixture")
    http_client = httpx.Client
    selected = {"version": 1, "selection": {"mode_id": "rainbow", "mode_version": 1}}

    def send(request):
        assert request.url.path == f"/api/v1/projects/{project}/team-selection"
        assert request.url.params["org_id"] == org
        if request.method == "GET":
            return httpx.Response(200, json={"version": 0, "selection": None})
        assert request.method == "PUT" and json.loads(request.content) == {"mode_id": "rainbow"}
        if request.headers["If-Match"] != '"0"':
            return httpx.Response(412, json={"code": "version_conflict"})
        return httpx.Response(200, json=selected)

    monkeypatch.setattr(web.httpx, "Client",
                        lambda **kwargs: http_client(**kwargs, transport=httpx.MockTransport(send)))
    runner = CliRunner()
    options = ["--org-id", org, "--project-id", project]
    read = runner.invoke(app, ["project", "team-show", *options])
    assert read.exit_code == 0 and json.loads(read.stdout)["version"] == 0
    select = ["project", "team-select", *options, "--mode", "rainbow", "--version"]
    result = runner.invoke(app, [*select, "0"])
    assert result.exit_code == 0 and json.loads(result.stdout) == selected
    stale = runner.invoke(app, [*select, "1"])
    assert stale.exit_code == 5 and "API 412 · version_conflict" in stale.stderr
