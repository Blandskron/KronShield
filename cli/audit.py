from application.audit_service import audit_website
from gpt import client, summarize
from reports import generator as report_gen
from domain.models import Finding
from infra.db import SessionLocal
from infra.repository import save_findings
import typer
import json

app = typer.Typer()

@app.command()
def run(
    url: str = typer.Option(..., "--url", "-u"),
    token: str = typer.Option(..., "--token", "-t"),
):
    client.init(token)
    typer.echo(f"Auditando {url}...")

    findings = audit_website(url)

    # Convert findings to JSON serializable
    serializable = [f.__dict__ for f in findings]

    # Guardar JSON local
    with open("output.json", "w") as f:
        json.dump({"url": url, "findings": serializable}, f, indent=2)
    typer.echo("Archivo 'output.json' generado.")

    # Generar reporte visual (PDF)
    report_path = report_gen.generate_pdf_report_from_json(url, serializable)
    typer.echo(f"Reporte PDF generado en: {report_path}")

    # Guardar en base de datos
    with SessionLocal() as db:
        save_findings(db, findings)
    typer.echo("Hallazgos guardados en base de datos.")
