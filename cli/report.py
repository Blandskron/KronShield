import typer
import json
from pathlib import Path
from gpt import summarize
from reports.generator import generate_pdf_report

app = typer.Typer(help="Genera reportes visuales desde auditorías guardadas")

@app.command("generate")
def generate(
    input: str = typer.Option(..., "--input", "-i", help="Archivo JSON con resultados de auditoría"),
    token: str = typer.Option(..., "--token", "-t", help="Token GPT válido"),
    format: str = typer.Option("pdf", "--format", "-f", help="Formato de salida (solo 'pdf')")
):
    path = Path(input)
    if not path.exists():
        typer.echo(f"❌ El archivo '{input}' no existe.")
        raise typer.Exit(1)

    with open(path, "r") as f:
        data = json.load(f)

    summarize.init(token)
    typer.echo("🤖 Consultando a GPT para redactar el informe...")
    content = summarize.generate_summary(data)

    if format == "pdf":
        output = generate_pdf_report(content)
        typer.echo(f"✅ Reporte PDF generado en: {output}")
    else:
        typer.echo("❌ Formato no soportado. Solo 'pdf' disponible.")
        raise typer.Exit(1)
