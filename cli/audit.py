import json
import os
from pathlib import Path
from urllib.parse import urlparse

import typer

from application.audit_service import audit_website
from gpt import client
from infra.db import SessionLocal
from infra.repository import save_findings

app = typer.Typer()


def validate_url(url: str):
    """Validate the URL has a scheme and network location; exit if invalid."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        typer.echo("URL inválida. Debe incluir http:// o https://")
        raise typer.Exit(1)


@app.command()
def run(
    url: str = typer.Option(..., "--url", "-u", help="URL a auditar"),
    token: str = typer.Option(
        None, "--token", "-t", envvar="GROQ_API_KEY",
        help="API key de Groq (por defecto GROQ_API_KEY del entorno)",
    ),
):
    """
    Ejecuta una auditoría web y guarda los resultados en JSON y en la base de datos.

    - Valida la URL de destino
    - Inicializa el cliente Groq (openai/gpt-oss-120b)
    - Ejecuta la auditoría (recon, puertos, XSS, SQLi)
    - Guarda hallazgos en results/{dominio}/{dominio}.json y en la base de datos
    """
    validate_url(url)
    token = token or os.getenv("GROQ_API_KEY")

    typer.echo(f"Auditando {url}...")

    try:
        client.init(token)
        findings = audit_website(url, token)
    except Exception as e:
        typer.echo(f"Error durante auditoría: {e}")
        raise typer.Exit(1)

    serializable = [f.__dict__ for f in findings]

    domain = urlparse(url).netloc.replace("www.", "")
    output_dir = Path("results") / domain
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{domain}.json"

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"url": url, "findings": serializable}, f, indent=2, ensure_ascii=False)
        typer.echo(f"Archivo JSON generado: {output_path}")
    except Exception as e:
        typer.echo(f"Error al guardar JSON: {e}")

    try:
        with SessionLocal() as db:
            save_findings(db, findings, url)
        typer.echo("Hallazgos guardados en base de datos.")
    except Exception as e:
        typer.echo(f"Error al guardar en la base de datos: {e}")

    typer.echo(f"Auditoría finalizada: {len(findings)} hallazgos.")
