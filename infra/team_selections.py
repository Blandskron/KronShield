"""Persist project team selections as independent, immutable revisions."""

from sqlalchemy import Connection, text

from application.access import AccessError, ProjectAccess
from domain.team_modes import TeamMode
from infra.engagements import inventory_item


def get_selection(connection: Connection, caller: ProjectAccess) -> dict | None:
    row = connection.execute(text("""
        SELECT version, mode_id, mode_version, mode_digest, actor_id, created_at
        FROM pentest_agent.project_team_selection
        WHERE org_id = :org AND project_id = :project
        ORDER BY version DESC LIMIT 1
    """), {"org": caller.org_id, "project": caller.project_id}).mappings().one_or_none()
    return dict(row) if row is not None else None


def set_selection(connection: Connection, caller: ProjectAccess, mode: TeamMode, expected_version: int) -> dict:
    lock = f"project-team-selection/{caller.org_id}/{caller.project_id}"
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock})
    project = inventory_item(connection, "project", caller.project_id)
    if project["state"] != "active":
        raise AccessError(409, "project_archived")
    current = get_selection(connection, caller)
    version = current["version"] if current is not None else 0
    if version != expected_version:
        raise AccessError(412, "version_conflict")
    if current is not None and current["mode_digest"] == mode.digest:
        return current
    row = connection.execute(text("""
        INSERT INTO pentest_agent.project_team_selection
            (org_id, project_id, version, mode_id, mode_version, mode_digest, actor_id)
        VALUES (:org, :project, :version, :mode, :mode_version, :digest, :actor)
        RETURNING version, mode_id, mode_version, mode_digest, actor_id, created_at
    """), {
        "org": caller.org_id, "project": caller.project_id, "version": version + 1,
        "mode": mode.id.value, "mode_version": mode.version, "digest": mode.digest, "actor": caller.user_id,
    }).mappings().one()
    return dict(row)
