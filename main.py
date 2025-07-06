from typer import Typer
from cli import audit, report

app = Typer()
app.add_typer(audit.app, name="audit")
app.add_typer(report.app, name="report")

if __name__ == "__main__":
    app()
