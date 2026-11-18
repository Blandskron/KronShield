"""Build a local HTML report from previously captured audit data."""

from pathlib import Path

import typer

from application.report_input import read_saved_audit
from gpt import client, summarize
from reports.report_html import generate_audit_html_report


app = typer.Typer(help="Genera reportes visuales desde auditorías guardadas.")


@app.command("generate")
def generate(
    input_file: Path = typer.Option(..., "--input", "-i", exists=True, dir_okay=False, readable=True),
    with_ai: bool = typer.Option(False, "--with-ai", help="Envía el tipo y detalle de los hallazgos a Groq."),
):
    try:
        audit = read_saved_audit(input_file)
    except (OSError, ValueError):
        typer.echo("Entrada inválida. Se espera un JSON de auditoría válido de hasta 1 MiB.", err=True)
        raise typer.Exit(2) from None

    summary = None
    if with_ai:
        try:
            client.init()
            summary = summarize.generate_summary(audit.summary_input())
        except Exception:
            typer.echo("No se pudo obtener el resumen de Groq. Revisa la configuración del proveedor.", err=True)
            raise typer.Exit(5) from None

    try:
        output = generate_audit_html_report(audit, summary)
    except (OSError, ValueError, RuntimeError):
        typer.echo("No se pudo publicar el informe en el directorio results.", err=True)
        raise typer.Exit(5) from None
    typer.echo(f"Reporte HTML generado en: {output}")
