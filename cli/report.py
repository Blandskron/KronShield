import json
import os
from pathlib import Path
from urllib.parse import urlparse

import typer

from gpt import summarize, client
from reports.report_html import generate_html_report

app = typer.Typer(help="Genera reportes visuales desde auditorías guardadas")


@app.command("generate")
def generate(
    input: str = typer.Option(..., "--input", "-i", help="Archivo JSON con resultados de auditoría"),
    token: str = typer.Option(
        None, "--token", "-t", envvar="GROQ_API_KEY",
        help="API key de Groq (por defecto GROQ_API_KEY del entorno)",
    ),
):
    path = Path(input)
    if not path.exists():
        typer.echo(f"El archivo '{input}' no existe.")
        raise typer.Exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    client.init(token or os.getenv("GROQ_API_KEY"))
    typer.echo("Consultando a Groq (openai/gpt-oss-120b) para redactar el informe...")
    content = summarize.generate_summary(data)

    domain = urlparse(data["url"]).netloc.replace("www.", "")
    output = generate_html_report(content, domain)
    typer.echo(f"Reporte HTML generado en: {output}")
