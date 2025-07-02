from typer import Typer
from cli import audit, report  # 👈 asegúrate de importar report.py también

app = Typer()
app.add_typer(audit.app, name="audit")
app.add_typer(report.app, name="report")  # 👈 registra el subcomando report

if __name__ == "__main__":
    app()
