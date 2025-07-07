from application.audit_service import audit_website
from gpt import client, summarize
from reports import generator as report_gen
from domain.models import Finding
from infra.db import SessionLocal
from infra.repository import save_findings
import typer
import json
from urllib.parse import urlparse
import os

app = typer.Typer()

def validate_url(url: str):
    """
    Validates that the provided URL contains a scheme and a network location.
    Exits the application if invalid.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        typer.echo("URL inválida. Debe incluir http:// o https://")
        raise typer.Exit(1)

@app.command()
def run(
    url: str = typer.Option(..., "--url", "-u", help="URL a auditar"),
    token: str = os.getenv("OPENAI_API_KEY"),
    output: str = typer.Option("output.json", "--output", "-o", help="Archivo de salida JSON"),
):
    """
    Main CLI entrypoint to execute a full audit workflow against a target URL.

    - Validates the target URL
    - Initializes GPT client for summarization
    - Executes audit and stores results in a JSON file
    - Generates a PDF report from audit findings
    - Persists findings in the database

    Args:
        url (str): Target website URL.
        token (str): OpenAI API token for report generation.
        output (str): Path to save the resulting JSON file.
    """
    validate_url(url)

    typer.echo(f"Auditando {url}...")

    try:
        client.init(token)
        findings = audit_website(url, token)
    except Exception as e:
        typer.echo(f"Error durante auditoría: {e}")
        raise typer.Exit(1)

    serializable = [f.__dict__ for f in findings]

    try:
        with open(output, "w") as f:
            json.dump({"url": url, "findings": serializable}, f, indent=2)
        typer.echo(f"Archivo JSON generado: {output}")
    except Exception as e:
        typer.echo(f"Error al guardar JSON: {e}")

    try:
        report_path = report_gen.generate_pdf_report_from_json(url, serializable, token)
        typer.echo(f"Reporte PDF generado: {report_path}")
    except Exception as e:
        typer.echo(f"Error al generar PDF: {e}")

    try:
        with SessionLocal() as db:
            save_findings(db, findings, url)
        typer.echo("Hallazgos guardados en base de datos.")
    except Exception as e:
        typer.echo(f"Error al guardar en la base de datos: {e}")
