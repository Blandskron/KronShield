from application.audit_service import audit_website
from gpt import client
from reports import generator as report_gen
from domain.models import Finding
import typer, json

app = typer.Typer()

@app.command()
def run(
    url: str = typer.Option(..., "--url", "-u"),
    token: str = typer.Option(..., "--token", "-t"),
):
    client.init(token)
    typer.echo(f"Auditando {url}...")

    findings = audit_website(url)
    serializable = [f.__dict__ for f in findings]

    with open("output.json", "w") as f:
        json.dump({"url": url, "findings": serializable}, f, indent=2)

    typer.echo("Archivo 'output.json' generado.")
