"""CLI commands for preparing plans and analyzing saved responses."""

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from application.audit_service import ActiveAuditDisabled, Profile, audit_website, prepare_plan
from core import settings, sqli, xss
from domain.authorization import Attribution
from domain.targets import canonical_http_target


app = typer.Typer(help="Planifica auditorías y analiza respuestas locales.")
_MAX_INPUT_BYTES = 256 * 1024


class OfflineCheck(str, Enum):
    XSS = "xss"
    SQLI = "sqli"


@app.command()
def run(
    url: str = typer.Option("", "--url", "-u", help="Destino del comando heredado. Ejecución deshabilitada."),
):
    """Indica el cierre del comando de auditoría activo."""
    try:
        audit_website(url)
    except ActiveAuditDisabled as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(4) from None


@app.command()
def plan(
    url: str = typer.Option(..., "--url", "-u", help="Destino HTTP(S) del plan."),
    profile: Profile = typer.Option(Profile.WEB_BASELINE, "--profile", help="Comprobación propuesta."),
    environment: str = typer.Option("lab", "--environment", help="Entorno previsto del objetivo."),
):
    """Valida la estructura de un plan local sin consultar la red."""
    try:
        target = canonical_http_target(url, environment=environment, attribution=Attribution.UNKNOWN)
        planned = prepare_plan(target, profile, settings.configuration().execution)
    except (OSError, ValueError) as error:
        typer.echo(f"Plan inválido. {error}", err=True)
        raise typer.Exit(2) from None

    typer.echo(json.dumps({
        "profile": planned.profile.value,
        "technique": planned.technique,
        "target": {
            "host": str(planned.target.host),
            "port": planned.target.port,
            "scheme": planned.target.scheme,
            "path": planned.target.path,
            "trailing_slash": planned.target.trailing_slash,
            "method": planned.target.method,
            "environment": planned.target.environment,
        },
        "scope": planned.scope.reason.value,
        "execution": "disabled",
        "limits": planned.limits.model_dump(),
    }, ensure_ascii=False))


@app.command()
def analyze(
    input_file: Path = typer.Option(..., "--input", "-i", exists=True, dir_okay=False, readable=True),
    check: OfflineCheck = typer.Option(..., "--check", help="Heurística local sobre el cuerpo guardado."),
    marker: Optional[str] = typer.Option(None, "--marker", help="Marcador de prueba original para XSS."),
):
    """Busca indicadores en un cuerpo HTTP guardado como texto UTF-8."""
    if check is OfflineCheck.XSS and not marker:
        typer.echo("El análisis XSS requiere --marker.", err=True)
        raise typer.Exit(2)
    if check is OfflineCheck.SQLI and marker is not None:
        typer.echo("--marker se usa con el análisis XSS.", err=True)
        raise typer.Exit(2)
    try:
        if not input_file.is_file():
            raise ValueError("El cuerpo guardado debe ser un archivo regular.")
        with input_file.open("rb") as source:
            content = source.read(_MAX_INPUT_BYTES + 1)
        if len(content) > _MAX_INPUT_BYTES:
            raise ValueError("El cuerpo guardado supera el límite de 256 KiB.")
        body = content.decode("utf-8")
    except UnicodeError:
        typer.echo("El cuerpo guardado debe estar codificado en UTF-8.", err=True)
        raise typer.Exit(2) from None
    except (OSError, ValueError):
        typer.echo("No se pudo leer el cuerpo guardado o supera 256 KiB.", err=True)
        raise typer.Exit(2) from None

    try:
        finding = xss.analyze(body, marker) if marker is not None else sqli.analyze(body)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps({
        "check": check.value,
        "findings": [asdict(finding)] if finding else [],
    }, ensure_ascii=False))
