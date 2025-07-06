from typer import Typer
from cli import audit, report
from dotenv import load_dotenv
import os
from pathlib import Path


env_path = Path("config") / ".env"
load_dotenv(dotenv_path=env_path)

app = Typer()
app.add_typer(audit.app, name="audit")
app.add_typer(report.app, name="report")

if __name__ == "__main__":
    app()
