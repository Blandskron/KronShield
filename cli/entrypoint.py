"""Installed CLI and compatibility entry point for main.py."""

from dotenv import load_dotenv
from typer import Typer

from cli import audit, report, web
from cli.legacy import import_legacy
from core.settings import configuration_path

app = Typer()
audit.app.command("import-legacy")(import_legacy)
app.add_typer(audit.app, name="audit")
app.add_typer(report.app, name="report")
app.command("status")(web.status)
app.add_typer(web.auth, name="auth")
app.add_typer(web.project, name="project")
app.add_typer(web.target, name="target")
app.add_typer(web.authorization, name="authorization")
app.add_typer(web.assessment, name="assessment")
app.add_typer(web.plan, name="plan")
app.add_typer(web.lab, name="lab")


@app.callback()
def load_environment() -> None:
    load_dotenv(configuration_path().with_name(".env"))
