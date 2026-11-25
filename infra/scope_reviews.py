"""Record assessments, scope-review snapshots and their audit events atomically."""

from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from application.access import AccessError, ProjectAccess
from application.scope_review import canonical_json, fingerprint, review
from infra.engagements import authorization, lock_authorization
from infra.tenancy import lock_organization_work


def _matching_row(connection: Connection, statement: str, parameters: dict, missing: str) -> dict:
    row = connection.execute(text(statement), parameters).mappings().one_or_none()
    if row is None:
        raise AccessError(404, missing)
    return dict(row)


def assessment(connection: Connection, assessment_id: UUID) -> dict:
    return _matching_row(connection, """
        SELECT id, actor_id, label, created_at FROM pentest_agent.assessment WHERE id = :id
    """, {"id": assessment_id}, "assessment_not_found")


def assessments(connection: Connection, after: UUID | None, limit: int) -> dict:
    rows = connection.execute(text("""
        SELECT id, actor_id, label, created_at FROM pentest_agent.assessment
        WHERE (CAST(:after AS uuid) IS NULL OR id > :after)
        ORDER BY id LIMIT :limit
    """), {"after": after, "limit": limit + 1}).mappings().all()
    page = rows[:limit]
    return {"items": [dict(row) for row in page], "next_cursor": page[-1]["id"] if len(rows) > limit else None}


def create_assessment(connection: Connection, caller: ProjectAccess, label: str) -> dict:
    row = connection.execute(text("""
        INSERT INTO pentest_agent.assessment (org_id, project_id, id, actor_id, label)
        VALUES (:org, :project, :id, :actor, :label)
        RETURNING id, actor_id, label, created_at
    """), {"org": caller.org_id, "project": caller.project_id, "id": uuid4(),
           "actor": caller.user_id, "label": label}).mappings().one()
    return dict(row)


def _current_review(connection: Connection, caller: ProjectAccess, selection: dict) -> tuple[dict, datetime]:
    lock_organization_work(connection, caller.org_id)
    authorization_id = UUID(selection["authorization_id"])
    lock_authorization(connection, caller.org_id, caller.project_id, authorization_id)
    latest = authorization(connection, authorization_id)
    requested = selection["authorization_revision"]
    record = latest if requested == latest["revision"] else authorization(connection, authorization_id, requested)
    state = _matching_row(connection, """
        SELECT p.version, p.state, o.kill_switch
        FROM pentest_agent.project p JOIN pentest_agent.organization o ON o.id = p.org_id
        WHERE p.id = :project AND o.id = :org AND o.state = 'active'
    """, {"project": caller.project_id, "org": caller.org_id}, "project_not_found")
    ids = [UUID(value) for value in selection["target_ids"]]
    rows = connection.execute(text("""
        SELECT id, version, canonical_address, environment, attribution, third_party_id
        FROM pentest_agent.target WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id
    """), {"ids": ids}).mappings().all()
    if len(rows) != len(ids):
        raise AccessError(404, "target_not_found")
    checked_at = datetime.now(timezone.utc)
    try:
        return review(str(caller.org_id), str(caller.project_id), state, selection, record,
                      latest["revision"], rows, checked_at), checked_at
    except ValueError:
        raise AccessError(409, "invalid_authorization_record") from None


PLAN_COLUMNS = "id, actor_id, digest AS hash, snapshot, checked_at"


def plan(connection: Connection, plan_id: UUID) -> dict:
    row = _matching_row(connection, f"""
        SELECT {PLAN_COLUMNS} FROM pentest_agent.assessment_plan WHERE id = :id
    """, {"id": plan_id}, "plan_not_found")
    return _plan_view(row)


def _plan_view(row) -> dict:
    return {"id": row["id"], "actor_id": row["actor_id"], "hash": row["hash"],
            "checked_at": row["checked_at"], **row["snapshot"]}


def create_plan(connection: Connection, caller: ProjectAccess, selection: dict, idempotency_key: str) -> dict:
    key_digest = sha256(idempotency_key.encode("ascii")).hexdigest()
    request_digest = fingerprint(selection)
    lock_name = f"scope-review/{caller.org_id}/{caller.project_id}/{caller.user_id}/{key_digest}"
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_name})
    previous = connection.execute(text(f"""
        SELECT {PLAN_COLUMNS}, request_digest FROM pentest_agent.assessment_plan
        WHERE actor_id = :actor AND idempotency_digest = :idempotency
    """), {"actor": caller.user_id, "idempotency": key_digest}).mappings().one_or_none()
    if previous:
        if previous["request_digest"] != request_digest:
            raise AccessError(409, "idempotency_conflict")
        return _plan_view(previous)

    assessment_id = UUID(selection["assessment_id"])
    assessment(connection, assessment_id)
    snapshot, checked_at = _current_review(connection, caller, selection)
    digest = fingerprint(snapshot)
    refs = {"org": caller.org_id, "project": caller.project_id, "plan": uuid4()}
    connection.execute(text("""
        INSERT INTO pentest_agent.assessment_plan (
            org_id, project_id, id, actor_id, assessment_id, authorization_id, authorization_revision,
            idempotency_digest, request_digest, digest, snapshot, checked_at
        ) VALUES (:org, :project, :plan, :actor, :assessment, :authorization, :revision,
                  :idempotency, :request, :digest, CAST(:snapshot AS jsonb), :checked)
    """), {**refs, "actor": caller.user_id, "assessment": assessment_id,
           "authorization": UUID(selection["authorization_id"]), "revision": selection["authorization_revision"],
           "idempotency": key_digest, "request": request_digest, "digest": digest,
           "snapshot": canonical_json(snapshot), "checked": checked_at})
    connection.execute(text("""
        INSERT INTO pentest_agent.assessment_plan_target (org_id, project_id, plan_id, target_id)
        VALUES (:org, :project, :plan, :target)
    """), [{**refs, "target": UUID(target)} for target in selection["target_ids"]])
    event = {**refs, "event": uuid4()}
    connection.execute(text("""
        INSERT INTO pentest_agent.assessment_plan_event (org_id, project_id, plan_id, id, kind)
        VALUES (:org, :project, :plan, :event, 'scope_review_recorded')
    """), event)
    connection.execute(text("""
        INSERT INTO pentest_agent.assessment_plan_outbox (org_id, project_id, plan_id, event_id)
        VALUES (:org, :project, :plan, :event)
    """), event)
    return {"id": refs["plan"], "actor_id": caller.user_id, "hash": digest, "checked_at": checked_at, **snapshot}


def plan_events(connection: Connection, plan_id: UUID) -> list[dict]:
    plan(connection, plan_id)
    rows = connection.execute(text("""
        SELECT id, kind, created_at FROM pentest_agent.assessment_plan_event WHERE plan_id = :id
        ORDER BY created_at, id
    """), {"id": plan_id}).mappings()
    return [dict(row) for row in rows]


def verify_plan(connection: Connection, caller: ProjectAccess, plan_id: UUID, expected_hash: str) -> dict:
    stored = plan(connection, plan_id)
    if not compare_digest(stored["hash"], expected_hash):
        raise AccessError(409, "plan_hash_mismatch")
    joined = stored["authorization"]
    current, _ = _current_review(connection, caller, {
        "assessment_id": stored["assessment_id"],
        "authorization_id": joined["id"],
        "authorization_revision": joined["revision"],
        "target_ids": [target["id"] for target in stored["targets"]],
    })
    if not compare_digest(fingerprint(current), expected_hash):
        raise AccessError(409, "plan_state_changed")
    if current["status"] == "blocked":
        raise AccessError(409, "plan_blocked")
    return {"id": plan_id, "hash": expected_hash, "status": "verified", "execution": "disabled"}
