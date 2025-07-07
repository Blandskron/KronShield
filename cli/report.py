import typer
import json
from pathlib import Path
from gpt import summarize, client
from reports.generator import generate_pdf_report
import os

app = typer.Typer(help="Genera reportes visuales desde auditorías guardadas")

@app.command("generate")
def generate(
    input: str = typer.Option(..., "--input", "-i", help="Archivo JSON con resultados de auditoría"),
    token: str = os.getenv("OPENAI_API_KEY"),
    format: str = typer.Option("pdf", "--format", "-f", help="Formato de salida (solo 'pdf')")
):
    """
    Generates a visual report (PDF) from a previously saved audit result file in JSON format.

    - Loads and validates the input JSON
    - Summarizes the findings using GPT
    - Generates a PDF report based on the summarized content

    Args:
        input (str): Path to the audit results JSON file.
        token (str): OpenAI API key used to generate summaries.
        format (str): Output format (currently only 'pdf' is supported).
    """
    path = Path(input)
    if not path.exists():
        typer.echo(f"El archivo '{input}' no existe.")
        raise typer.Exit(1)

    with open(path, "r") as f:
        data = json.load(f)

    client.init(token)
    typer.echo("Consultando a GPT para redactar el informe...")
    content = summarize.generate_summary(data)

    if format == "pdf":
        output = generate_pdf_report(content)
        typer.echo(f"Reporte PDF generado en: {output}")
    else:
        typer.echo("Formato no soportado. Solo 'pdf' disponible.")
        raise typer.Exit(1)
