"""SQL operations on connections scoped by the authenticated request."""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from application.access import AccessError


COLUMNS = {
    "organization": "id, slug, state, version",
    "customer": "org_id, id, slug, name, version",
    "project": "org_id, id, customer_id, slug, environment, state, version",
    "target": "org_id, project_id, id, slug, environment, canonical_address, attribution, third_party_id, version",
}


def is_platform_admin(connection: Connection, user_id: UUID) -> bool:
    return connection.scalar(text("SELECT user_id FROM pentest_agent.platform_admin WHERE user_id = :user"),
                             {"user": user_id}) is not None


def organization_role(connection: Connection, user_id: UUID, org_id: UUID) -> str | None:
    return connection.scalar(text("""
        SELECT role_id FROM pentest_agent.organization_membership WHERE org_id = :org AND user_id = :user
    """), {"org": org_id, "user": user_id})


def inventory_page(connection: Connection, resource: str, after: UUID | None, limit: int) -> dict:
    rows = connection.execute(text(f"""
        SELECT {COLUMNS[resource]} FROM pentest_agent.{resource}
        WHERE (CAST(:after AS uuid) IS NULL OR id > :after)
        ORDER BY id LIMIT :limit
    """), {"after": after, "limit": limit + 1}).mappings().all()
    return _page(rows, limit)


def _page(rows, limit: int) -> dict:
    visible = rows[:limit]
    return {"items": [dict(row) for row in visible], "next_cursor": visible[-1]["id"] if len(rows) > limit else None}


def inventory_item(connection: Connection, resource: str, item_id: UUID) -> dict:
    row = connection.execute(text(f"SELECT {COLUMNS[resource]} FROM pentest_agent.{resource} WHERE id = :id"),
                             {"id": item_id}).mappings().one_or_none()
    if row is None:
        raise AccessError(404, f"{resource}_not_found")
    return dict(row)


def insert_inventory(connection: Connection, resource: str, values: dict) -> None:
    # Keys come from the request models' explicitly selected fields, or server-generated IDs.
    columns = ", ".join(values)
    placeholders = ", ".join(f":{key}" for key in values)
    connection.execute(text(f"INSERT INTO pentest_agent.{resource} ({columns}) VALUES ({placeholders})"), values)


def change_inventory(connection: Connection, resource: str, item_id: UUID, version: int, changes: dict) -> dict:
    assignments = ", ".join(f"{key} = :{key}" for key in changes)
    row = connection.execute(text(f"""
        UPDATE pentest_agent.{resource} SET {assignments}, version = version + 1
        WHERE id = :id AND version = :expected_version
        RETURNING {COLUMNS[resource]}
    """), {**changes, "id": item_id, "expected_version": version}).mappings().one_or_none()
    if row is None:
        inventory_item(connection, resource, item_id)
        raise AccessError(412, "version_mismatch")
    return dict(row)


def remove_inventory(connection: Connection, resource: str, item_id: UUID, version: int) -> None:
    removed = connection.execute(text(f"DELETE FROM pentest_agent.{resource} WHERE id = :id AND version = :version"),
                                 {"id": item_id, "version": version}).rowcount
    if removed == 0:
        inventory_item(connection, resource, item_id)
        raise AccessError(412, "version_mismatch")


def store_document(connection: Connection, values: dict) -> dict:
    row = connection.execute(text("""
        INSERT INTO pentest_agent.authorization_document
            (org_id, project_id, id, uploader_id, digest, nonce, ciphertext)
        VALUES (:org, :project, :id, :actor, :digest, :nonce, :ciphertext)
        RETURNING id, digest, created_at
    """), values).mappings().one()
    return dict(row)


def document(connection: Connection, document_id: UUID, *, content: bool = False) -> dict:
    columns = "digest, nonce, ciphertext" if content else "digest"
    row = connection.execute(text(f"SELECT {columns} FROM pentest_agent.authorization_document WHERE id = :id"),
                             {"id": document_id}).mappings().one_or_none()
    if row is None:
        raise AccessError(404, "document_not_found")
    return dict(row)


AUTHORIZATION_SELECT = """
    SELECT a.id, a.revision, a.requester_id, a.delegator_id, a.document_id AS document_evidence_id,
           a.document_digest, a.environment, a.valid_from, a.valid_until, a.scope_rules, a.limits, a.created_at,
           CASE WHEN r.actor_id IS NOT NULL THEN 'revoked'
                WHEN p.actor_id IS NOT NULL THEN 'approved' ELSE a.status END AS status,
           COALESCE(p.actor_id, a.verifier_id) AS verifier_id,
           p.reason AS approval_reason, p.created_at AS approved_at,
           r.actor_id AS revoked_by, r.reason AS revocation_reason, r.created_at AS revoked_at
    FROM pentest_agent.authorization a
    LEFT JOIN pentest_agent.authorization_decision p
      ON (p.org_id, p.project_id, p.authorization_id, p.revision) = (a.org_id, a.project_id, a.id, a.revision)
      AND p.decision = 'approve'
    LEFT JOIN pentest_agent.authorization_decision r
      ON (r.org_id, r.project_id, r.authorization_id, r.revision) = (a.org_id, a.project_id, a.id, a.revision)
      AND r.decision = 'revoke'
"""


def _view(row) -> dict:
    snapshot = dict(row)
    status = snapshot["status"]
    if status == "approved":
        now = datetime.now(timezone.utc)
        status = ("expired" if snapshot["valid_until"] <= now else
                  "scheduled" if snapshot["valid_from"] > now else "active")
    snapshot["effective_status"] = status
    return snapshot


def authorizations(connection: Connection, after: UUID | None, limit: int) -> dict:
    rows = connection.execute(text(AUTHORIZATION_SELECT + """
        WHERE (CAST(:after AS uuid) IS NULL OR a.id > :after)
          AND a.revision = (SELECT max(r.revision) FROM pentest_agent.authorization AS r
                            WHERE (r.org_id, r.project_id, r.id) = (a.org_id, a.project_id, a.id))
        ORDER BY a.id LIMIT :limit
    """), {"after": after, "limit": limit + 1}).mappings()
    return _page([_view(row) for row in rows], limit)


def authorization(connection: Connection, authorization_id: UUID, revision: int | None = None) -> dict:
    row = connection.execute(text(AUTHORIZATION_SELECT + """
        WHERE a.id = :id AND (CAST(:revision AS integer) IS NULL OR a.revision = :revision)
        ORDER BY a.revision DESC LIMIT 1
    """), {"id": authorization_id, "revision": revision}).mappings().one_or_none()
    if row is None:
        raise AccessError(404, "authorization_not_found")
    return _view(row)


def lock_authorization(connection: Connection, org_id: UUID, project_id: UUID, authorization_id: UUID) -> None:
    key = f"{org_id}/{project_id}/{authorization_id}"
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def save_authorization(
    connection: Connection, org_id: UUID, project_id: UUID, user_id: UUID, values: dict,
    authorization_id: UUID | None = None, previous: int | None = None,
) -> dict:
    if authorization_id is None:
        authorization_id, revision = uuid4(), 1
    else:
        lock_authorization(connection, org_id, project_id, authorization_id)
        current = authorization(connection, authorization_id)
        if current["revision"] != previous or current["effective_status"] not in {"draft", "revoked", "expired"}:
            raise AccessError(409, "revision_conflict")
        revision = current["revision"] + 1
    if values["valid_until"] <= datetime.now(timezone.utc):
        raise AccessError(422, "authorization_expired")
    document_id = values["document_evidence_id"]
    digest = document(connection, document_id)["digest"]
    environment = inventory_item(connection, "project", project_id)["environment"]
    connection.execute(text("""
        INSERT INTO pentest_agent.authorization
          (org_id, project_id, id, revision, requester_id, delegator_id, document_reference, document_id,
           document_digest, status, environment, valid_from, valid_until, scope_rules, limits)
        VALUES (:org, :project, :id, :revision, :actor, :delegator, :reference, :document,
                :digest, 'draft', :environment, :valid_from, :valid_until,
                CAST(:scope_rules AS jsonb), CAST(:limits AS jsonb))
    """), {"org": org_id, "project": project_id, "id": authorization_id, "revision": revision,
           "actor": user_id, "delegator": values["delegator_id"], "reference": str(document_id), "document": document_id, "digest": digest,
           "environment": environment, "valid_from": values["valid_from"], "valid_until": values["valid_until"],
           "scope_rules": json.dumps(values["scope_rules"]), "limits": json.dumps(values["limits"])})
    return authorization(connection, authorization_id, revision)


def decide_authorization(connection: Connection, org_id: UUID, project_id: UUID, user_id: UUID,
                         authorization_id: UUID, revision: int, decision: str, reason: str) -> dict:
    lock_authorization(connection, org_id, project_id, authorization_id)
    current = authorization(connection, authorization_id)
    if current["requester_id"] == user_id:
        raise AccessError(403, "approval_requires_distinct_actor")
    if revision != current["revision"] or current["status"] != {"approve": "draft", "revoke": "approved"}[decision]:
        raise AccessError(409, "revision_conflict")
    if decision == "approve" and inventory_item(connection, "project", project_id)["state"] == "archived":
        raise AccessError(409, "project_archived")
    if decision == "approve" and current["valid_until"] <= datetime.now(timezone.utc):
        raise AccessError(409, "authorization_expired")
    connection.execute(text("""
        INSERT INTO pentest_agent.authorization_decision
            (org_id, project_id, authorization_id, revision, decision, actor_id, reason)
        VALUES (:org, :project, :id, :revision, :decision, :actor, :reason)
    """), {"org": org_id, "project": project_id, "id": authorization_id, "revision": revision,
           "decision": decision, "actor": user_id, "reason": reason})
    return authorization(connection, authorization_id, revision)
