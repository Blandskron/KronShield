from application.audit_service import audit_website
from gpt import client
from domain.models import Finding
from infra.db import SessionLocal
from infra.repository import save_findings
import typer
import json
from urllib.parse import urlparse
import os
from pathlib import Path

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
):
    """
    Ejecuta una auditoría web y guarda los resultados en un archivo JSON y en la base de datos.

    - Valida la URL de destino
    - Inicializa el cliente GPT
    - Ejecuta la auditoría contra la URL objetivo
    - Guarda los hallazgos como JSON (en carpeta 'results')
    - Inserta los hallazgos en la base de datos
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

    # Extraer dominio y definir path de salida
    domain = urlparse(url).netloc.replace("www.", "")
    output_dir = Path("results") / domain
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{domain}.json"

    try:
        with open(output_path, "w") as f:
            json.dump({"url": url, "findings": serializable}, f, indent=2)
        typer.echo(f"Archivo JSON generado: {output_path}")
    except Exception as e:
        typer.echo(f"Error al guardar JSON: {e}")

    try:
        with SessionLocal() as db:
            save_findings(db, findings, url)
        typer.echo("Hallazgos guardados en base de datos.")
    except Exception as e:
        typer.echo(f"Error al guardar en la base de datos: {e}")
