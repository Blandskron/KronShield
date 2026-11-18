"""CLI commands for preparing plans and analyzing saved responses."""

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from application.audit_service import ActiveAuditDisabled, Profile, audit_website, prepare_plan
from application.report_input import read_saved_audit
from application.save_result import ResultPersistenceFailure, save_result
from core import settings, sqli, xss
from domain.authorization import Attribution
from domain.targets import canonical_http_target
from infra.offline_results import persist_offline_result


app = typer.Typer(help="Planifica auditorías y analiza respuestas locales.")
_MAX_INPUT_BYTES = 256 * 1024


class OfflineCheck(str, Enum):
    XSS = "xss"
    SQLI = "sqli"


@app.command()
def save(
    input_file: Path = typer.Option(..., "--input", "-i", exists=True, dir_okay=False, readable=True),
    database: Path = typer.Option(Path("pentest.db"), "--database", dir_okay=False),
):
    """Conserva una captura JSON de auditoría en un archivo nuevo y en SQLite."""
    try:
        audit = read_saved_audit(input_file)
    except (OSError, ValueError):
        typer.echo("Entrada inválida. Se espera un JSON de auditoría válido de hasta 1 MiB.", err=True)
        raise typer.Exit(2) from None
    try:
        result_id, output = save_result(
            audit, lambda snapshot, digest: persist_offline_result(database, snapshot, digest),
        )
    except ResultPersistenceFailure as error:
        typer.echo(json.dumps({
            "result_id": error.result_id, "snapshot": error.snapshot_path, "persistence": "json_only",
        }))
        typer.echo("Falló la escritura en SQLite. Conserva el JSON generado y úsalo con audit save para reintentar.", err=True)
        raise typer.Exit(5) from None
    except (OSError, ValueError):
        typer.echo("No se pudo publicar el resultado JSON.", err=True)
        raise typer.Exit(5) from None
    typer.echo(json.dumps({"result_id": result_id, "snapshot": output, "persistence": "complete"}))


def _read_capture(path: Path) -> str:
    if not path.is_file():
        raise ValueError("La captura debe ser un archivo regular.")
    with path.open("rb") as source:
        content = source.read(_MAX_INPUT_BYTES + 1)
    if len(content) > _MAX_INPUT_BYTES:
        raise ValueError("La captura supera el límite de 256 KiB.")
    return content.decode("utf-8")


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
    input_file: Optional[Path] = typer.Option(None, "--input", "-i", exists=True, dir_okay=False, readable=True),
    check: OfflineCheck = typer.Option(..., "--check", help="Heurística local sobre el cuerpo guardado."),
    marker: Optional[str] = typer.Option(None, "--marker", help="Marcador de prueba original para XSS."),
    baseline: Optional[Path] = typer.Option(None, "--baseline", exists=True, dir_okay=False, readable=True),
    content_type: Optional[str] = typer.Option(None, "--content-type", help="Tipo de contenido capturado para XSS."),
    response_missing: bool = typer.Option(False, "--response-missing", help="Registra una respuesta de prueba perdida."),
):
    """Busca indicadores en un cuerpo HTTP guardado como texto UTF-8."""
    if check is OfflineCheck.XSS and not marker:
        typer.echo("El análisis XSS requiere --marker.", err=True)
        raise typer.Exit(2)
    if check is OfflineCheck.SQLI and (marker is not None or content_type is not None):
        typer.echo("--marker y --content-type se usan con el análisis XSS.", err=True)
        raise typer.Exit(2)
    if response_missing == (input_file is not None):
        typer.echo("Usa --input para una captura o --response-missing si se perdió la respuesta.", err=True)
        raise typer.Exit(2)
    try:
        body = _read_capture(input_file) if input_file is not None else None
        reference = _read_capture(baseline) if baseline is not None else None
    except UnicodeError:
        typer.echo("El cuerpo guardado debe estar codificado en UTF-8.", err=True)
        raise typer.Exit(2) from None
    except (OSError, ValueError):
        typer.echo("No se pudo leer el cuerpo guardado o supera 256 KiB.", err=True)
        raise typer.Exit(2) from None

    try:
        if marker is not None:
            finding = xss.analyze(body, marker, baseline=reference, content_type=content_type)
        else:
            finding = sqli.analyze(body, baseline=reference)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps({
        "check": check.value,
        "findings": [asdict(finding)] if finding else [],
    }, ensure_ascii=False))
