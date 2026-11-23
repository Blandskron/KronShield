"""Validate or import legacy results through the authenticated API."""

import json
import os
from pathlib import Path
from typing import Optional
from uuid import UUID

import httpx
import typer

from application.legacy_import import FileFormat, parse_source, read_source


def import_legacy(
    source: Path = typer.Option(..., "--input"),
    format: FileFormat = typer.Option(..., "--format"),
    org_id: UUID = typer.Option(..., "--org-id"),
    project_id: UUID = typer.Option(..., "--project-id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    api_url: Optional[str] = typer.Option(None, "--api-url"),
) -> None:
    """Importa evidencia histórica sin modificar el archivo de origen."""
    try:
        raw = read_source(source, format)
        batch = parse_source(raw, format)
    except (OSError, ValueError):
        typer.echo("Origen histórico inválido, no regular o fuera de los límites.", err=True)
        raise typer.Exit(2) from None
    if dry_run:
        typer.echo(json.dumps({**batch.summary(), "org_id": str(org_id), "project_id": str(project_id),
                               "dry_run": True}))
        return

    secret = os.environ.get("PENTEST_AGENT_API_TOKEN")
    try:
        origin = httpx.URL(api_url or "")
        if (not secret or origin.scheme != "https" or not origin.host or origin.userinfo
                or origin.path != "/" or origin.query or origin.fragment):
            raise ValueError("Missing API context")
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                origin.copy_with(path=f"/api/v1/projects/{project_id}/legacy-imports"),
                params={"org_id": str(org_id), "format": format.value},
                headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/octet-stream"},
                content=raw,
            )
            response.raise_for_status()
            result = response.json()
            summary = {key: result[key] for key in (*batch.summary(), "id", "duplicate")}
    except (ValueError, httpx.HTTPError, httpx.InvalidURL, KeyError, TypeError):
        typer.echo("Importación rechazada. Verifica el origen HTTPS de la API, el token y los permisos del proyecto.",
                   err=True)
        raise typer.Exit(5) from None
    typer.echo(json.dumps(summary))
