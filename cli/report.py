import typer
import json
from pathlib import Path
from gpt import summarize, client
from reports.report_html import generate_html_report
import os
from urllib.parse import urlparse

app = typer.Typer(help="Genera reportes visuales desde auditorías guardadas")

@app.command("generate")
def generate(
    input: str = typer.Option(..., "--input", "-i", help="Archivo JSON con resultados de auditoría"),
    token: str = os.getenv("OPENAI_API_KEY"),
):
    path = Path(input)
    if not path.exists():
        typer.echo(f"El archivo '{input}' no existe.")
        raise typer.Exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    client.init(token)
    typer.echo("Consultando a GPT para redactar el informe...")
    content = summarize.generate_summary(data)

    domain = urlparse(data["url"]).netloc.replace("www.", "")
    output = generate_html_report(content, domain)
    typer.echo(f"Reporte HTML generado en: {output}")
