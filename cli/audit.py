import typer
from gpt import client
from core import recon, scanner, xss, sqli, report

app = typer.Typer(help="Auditoría automatizada de sitios web con soporte GPT")

@app.command("run")
def audit_command(
    url: str = typer.Option(..., "--url", "-u", help="URL a auditar"),
    token: str = typer.Option(..., "--token", "-t", help="Token GPT requerido")
):
    """Ejecuta una auditoría completa a la URL con payloads generados por GPT."""
    client.init(token)
    typer.echo(f"🔐 Token verificado. Iniciando auditoría de: {url}")

    info = recon.run(url)
    ports = scanner.scan_ports(url)
    xss_results = xss.test(url)
    sqli_results = sqli.test(url)

    findings = info + ports + xss_results + sqli_results
    report.generate(url, findings)
    typer.echo("✅ Auditoría finalizada. Reporte generado.")
