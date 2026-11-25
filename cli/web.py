"""Typer client for authenticated inventory and offline scope review."""

import json
import os
import shlex
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
import typer

from domain.team_modes import TeamId


auth = typer.Typer(no_args_is_help=True)
project = typer.Typer(no_args_is_help=True)
target = typer.Typer(no_args_is_help=True)
authorization = typer.Typer(no_args_is_help=True)
assessment = typer.Typer(no_args_is_help=True)
plan = typer.Typer(no_args_is_help=True)
lab = typer.Typer(no_args_is_help=True)


class APIError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


def _origin() -> httpx.URL:
    value = httpx.URL(os.getenv("PENTEST_AGENT_API_URL", "http://localhost:8080"))
    loopback = value.scheme == "http" and value.host in {"localhost", "127.0.0.1"}
    gateway = (value.scheme == "http" and value.host == "gateway" and value.port == 8080
               and os.getenv("PENTEST_AGENT_PILOT_GATEWAY") == "1")
    if (not value.host or not (value.scheme == "https" or loopback or gateway)
            or value.userinfo or value.path != "/" or value.query or value.fragment):
        raise ValueError("Configura un origen HTTPS o el gateway local del piloto.")
    return value


def _state_file() -> Path:
    return Path(os.getenv("PENTEST_AGENT_CLI_STATE", str(Path.home() / ".pentest-agent"))) / "session.json"


def _saved_token(origin: httpx.URL) -> str | None:
    file = _state_file()
    if os.name != "posix" or file.is_symlink() or not file.is_file() or file.stat().st_mode & 0o077:
        return None
    try:
        with file.open("rb") as source:
            data = json.loads(source.read(16385))
        return data["token"] if data["origin"] == str(origin) and isinstance(data["token"], str) else None
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _save_token(origin: httpx.URL, token: str) -> None:
    if os.name != "posix":
        raise ValueError("Usa el contenedor CLI del piloto para guardar la sesión.")
    destination = _state_file()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.parent.is_symlink() or destination.parent.stat().st_mode & 0o077:
        raise ValueError("El directorio de credenciales debe ser de acceso exclusivo.")
    with NamedTemporaryFile(mode="w", dir=destination.parent, encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump({"origin": str(origin), "token": token}, handle)
            handle.close()
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def _request(http: httpx.Client, method: str, path: str, *, raw=False, **kwargs):
    response = http.request(method, "/api/v1" + path, **kwargs)
    if not response.is_success:
        try:
            code = response.json().get("code", "request_failed")
        except (ValueError, AttributeError):
            code = "request_failed"
        raise APIError(response.status_code, code if isinstance(code, str) and code.isascii()
                       and code.replace("_", "a").isalnum() else "request_failed")
    return response if raw else response.json() if response.content else None


@contextmanager
def client(*, authenticated=True):
    try:
        origin = _origin()
        token = (os.getenv("PENTEST_AGENT_API_TOKEN") or _saved_token(origin)) if authenticated else None
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with httpx.Client(base_url=origin, headers=headers, timeout=15, follow_redirects=False, trust_env=False) as http:
            yield http
    except APIError as error:
        typer.echo(f"API {error.status} · {error.code}", err=True)
        exits = {401: 3, 403: 4, 422: 2, 428: 2, 503: 7}
        raise typer.Exit(exits.get(error.status, 5)) from None
    except httpx.HTTPError:
        typer.echo("La API no está disponible.", err=True)
        raise typer.Exit(7) from None
    except (ValueError, OSError, httpx.InvalidURL):
        typer.echo("Configuración de API, credenciales o respuesta inválida.", err=True)
        raise typer.Exit(2) from None


def _emit(value) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _params(org: UUID, after: Optional[UUID] = None) -> dict:
    result = {"org_id": str(org), "limit": 100}
    if after:
        result["after"] = str(after)
    return result


def _browser_url(org: UUID, proj: UUID, review: str) -> str:
    origin = os.getenv("PENTEST_AGENT_BROWSER_ORIGIN") or str(_origin())
    base = httpx.URL(origin)
    if not base.host or base.scheme not in {"http", "https"} or base.userinfo or base.query or base.fragment:
        raise ValueError("Invalid browser origin")
    return str(base).rstrip("/") + "/#plan?" + urlencode({"org": str(org), "project": str(proj), "id": review})


def shell_command(arguments: list[str], shell: str) -> str:
    if shell == "bash":
        return shlex.join(arguments)
    if shell == "powershell":
        return "& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
    raise ValueError("Unknown shell")


def _plan_output(data: dict, org: UUID, project_id: UUID) -> dict:
    plan_id = data["id"]
    command = ["pentest-agent", "plan", "show", "--org-id", str(org),
               "--project-id", str(project_id), "--plan-id", plan_id]
    return {**data, "browser_url": _browser_url(org, project_id, plan_id),
            "commands": {shell: shell_command(command, shell) for shell in ("bash", "powershell")}}


def status() -> None:
    """Consulta salud y disponibilidad del servicio."""
    with client(authenticated=False) as http:
        _emit({"health": _request(http, "GET", "/health"), "ready": _request(http, "GET", "/ready")})


@auth.command()
def login(username: str = typer.Option(..., "--username"), password_stdin: bool = typer.Option(False, "--password-stdin")):
    """Inicia una sesión de CLI en el piloto local."""
    if os.name != "posix":
        typer.echo("Usa docker compose run --rm cli auth login en Windows.", err=True)
        raise typer.Exit(2)
    password = sys.stdin.readline().rstrip("\r\n") if password_stdin else typer.prompt("Contraseña", hide_input=True)
    with client(authenticated=False) as http:
        if _request(http, "GET", "/auth/mode")["mode"] != "pilot":
            typer.echo("Para OIDC, define PENTEST_AGENT_API_TOKEN con un access token vigente.", err=True)
            raise typer.Exit(2)
        data = _request(http, "POST", "/auth/local/token", json={"username": username, "password": password})
        _save_token(_origin(), data["access_token"])
        _emit({"session": "active", "expires_in": data["expires_in"]})


@auth.command()
def whoami():
    with client() as http:
        data = _request(http, "GET", "/me")
        _emit({key: value for key, value in data.items() if key != "csrf_token"})


@auth.command()
def logout():
    with client() as http:
        mode = _request(http, "GET", "/auth/mode")["mode"]
        if mode == "pilot":
            try:
                _request(http, "POST", "/auth/local/revoke")
            except APIError as error:
                if error.status != 401:
                    raise
        destination = _state_file()
        if _saved_token(_origin()):
            destination.unlink()
        _emit({"session": "external" if mode == "oidc" and os.getenv("PENTEST_AGENT_API_TOKEN") else "closed", "provider": mode})


@project.command("organizations")
def organizations(after: Optional[UUID] = typer.Option(None, "--after")):
    with client() as http:
        _emit(_request(http, "GET", "/organizations", params={"limit": 100, **({"after": str(after)} if after else {})}))


def _project_list(resource, org_id, project_id, after):
    with client() as http:
        _emit(_request(http, "GET", f"/projects/{project_id}/{resource}", params=_params(org_id, after)))


@project.command("list")
def list_projects(org_id: UUID = typer.Option(..., "--org-id"), after: Optional[UUID] = typer.Option(None, "--after")):
    with client() as http:
        _emit(_request(http, "GET", "/projects", params=_params(org_id, after)))


@project.command("team-modes")
def project_team_modes(org_id: UUID = typer.Option(...), project_id: UUID = typer.Option(...)) -> None:
    """Consulta las especialidades y su disponibilidad."""
    with client() as http:
        _emit(_request(http, "GET", f"/projects/{project_id}/team-modes", params={"org_id": str(org_id)}))


@project.command("team-show")
def project_team_show(org_id: UUID = typer.Option(...), project_id: UUID = typer.Option(...)) -> None:
    """Consulta la especialidad guardada y su revisión."""
    with client() as http:
        _emit(_request(http, "GET", f"/projects/{project_id}/team-selection", params={"org_id": str(org_id)}))


@project.command("team-select")
def project_team_select(org_id: UUID = typer.Option(...), project_id: UUID = typer.Option(...),
                        mode: TeamId = typer.Option(...), version: int = typer.Option(..., min=0)) -> None:
    """Guarda la especialidad con la revisión obtenida mediante team-show."""
    with client() as http:
        _emit(_request(http, "PUT", f"/projects/{project_id}/team-selection", params={"org_id": str(org_id)},
                       headers={"If-Match": f'"{version}"'}, json={"mode_id": mode.value}))


@target.command("list")
def list_targets(org_id: UUID = typer.Option(..., "--org-id"), project_id: UUID = typer.Option(..., "--project-id"),
                 after: Optional[UUID] = typer.Option(None, "--after")):
    _project_list("targets", org_id, project_id, after)


@authorization.command("list")
def list_authorizations(org_id: UUID = typer.Option(..., "--org-id"), project_id: UUID = typer.Option(..., "--project-id"),
                        after: Optional[UUID] = typer.Option(None, "--after")):
    _project_list("authorizations", org_id, project_id, after)


@assessment.command("list")
def list_assessments(org_id: UUID = typer.Option(..., "--org-id"), project_id: UUID = typer.Option(..., "--project-id"),
                     after: Optional[UUID] = typer.Option(None, "--after")):
    _project_list("assessments", org_id, project_id, after)


@assessment.command("create")
def create_assessment(org_id: UUID = typer.Option(..., "--org-id"), project_id: UUID = typer.Option(..., "--project-id"),
                      label: str = typer.Option(..., "--label")):
    with client() as http:
        _emit(_request(http, "POST", f"/projects/{project_id}/assessments",
                       params={"org_id": str(org_id)}, json={"label": label}))


@plan.command("create")
def create_plan(
    org_id: UUID = typer.Option(..., "--org-id"),
    project_id: UUID = typer.Option(..., "--project-id"),
    assessment_id: UUID = typer.Option(..., "--assessment-id"),
    authorization_id: UUID = typer.Option(..., "--authorization-id"),
    revision: int = typer.Option(..., "--revision", min=1, max=2147483647),
    target_id: list[UUID] = typer.Option(..., "--target-id"),
    idempotency_key: Optional[str] = typer.Option(None, "--idempotency-key"),
):
    with client() as http:
        data = _request(http, "POST", f"/projects/{project_id}/plans", params={"org_id": str(org_id)},
                        headers={"Idempotency-Key": idempotency_key or uuid4().hex},
                        json={"assessment_id": str(assessment_id), "authorization_id": str(authorization_id),
                              "authorization_revision": revision, "target_ids": [str(item) for item in target_id],
                              "profile_id": "scope-review"})
        _emit(_plan_output(data, org_id, project_id))


@plan.command("show")
def show_plan(
    org_id: UUID = typer.Option(..., "--org-id"), project_id: UUID = typer.Option(..., "--project-id"),
    plan_id: UUID = typer.Option(..., "--plan-id"),
):
    with client() as http:
        data = _request(http, "GET", f"/projects/{project_id}/plans/{plan_id}", params={"org_id": str(org_id)})
        _emit(_plan_output(data, org_id, project_id))


@plan.command("report")
def report_plan(
    org_id: UUID = typer.Option(..., "--org-id"), project_id: UUID = typer.Option(..., "--project-id"),
    plan_id: UUID = typer.Option(..., "--plan-id"),
):
    """Envía el informe HTML de una revisión guardada a stdout."""
    with client() as http:
        response = _request(http, "GET", f"/projects/{project_id}/plans/{plan_id}/report",
                            params={"org_id": str(org_id)}, raw=True)
        if response.headers.get("Content-Type", "").split(";")[0].strip() != "text/html":
            raise ValueError("Unexpected report media type")
        sys.stdout.buffer.write(response.content)


@lab.command()
def seed(org_id: UUID = typer.Option(..., "--org-id"), project_id: UUID = typer.Option(..., "--project-id")):
    """Crea un activo de ejemplo en el inventario del laboratorio."""
    with client() as http:
        if _request(http, "GET", "/auth/mode")["mode"] != "pilot":
            raise APIError(403, "pilot_required")
        context = {"org_id": str(org_id)}
        selected = _request(http, "GET", f"/projects/{project_id}", params=context)
        if selected["environment"] != "lab" or selected["state"] != "active":
            raise APIError(403, "active_lab_required")
        path = f"/projects/{project_id}/targets"
        address = "https://lab.example/"

        def existing():
            next_cursor = None
            while True:
                page = _request(http, "GET", path, params=_params(org_id, next_cursor))
                match = next((item for item in page["items"]
                              if item["canonical_address"] == address and item["environment"] == "lab"), None)
                if match or not page["next_cursor"]:
                    return match
                next_cursor = page["next_cursor"]

        record = existing()
        if record is None:
            try:
                record = _request(http, "POST", path, params=context,
                                  json={"slug": "lab-asset", "address": address,
                                        "environment": "lab", "attribution": "first_party"})
            except APIError as error:
                if error.status != 409:
                    raise
                record = existing()
                if record is None:
                    raise
        _emit(record)
