"""Project-scoped storage and admission for offline evidence."""

import json
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from application import evidence
from application.access import AccessError, ProjectAccess
from application.documents import DocumentCipher
from application.scope_review import fingerprint
from infra.scope_reviews import plan, verify_plan


def _context(caller: ProjectAccess) -> dict:
    return {"org": caller.org_id, "project": caller.project_id, "actor": caller.user_id}


def _lock(connection: Connection, caller: ProjectAccess, key: str) -> None:
    name = f"evidence/{caller.org_id}/{caller.project_id}/{key}"
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": name})


def get_permission(connection: Connection, caller: ProjectAccess, permission_id: UUID,
                   revision: int | None = None) -> dict:
    row = connection.execute(text("""
        SELECT p.id, p.revision, p.requester_id, p.spec, p.created_at,
               a.actor_id AS approver_id, a.reason AS approval_reason, a.created_at AS approved_at,
               r.actor_id AS revoked_by, r.reason AS revocation_reason, r.created_at AS revoked_at,
               CASE WHEN r.kind IS NOT NULL THEN 'revoked'
                    WHEN a.kind IS NOT NULL THEN 'approved' ELSE 'pending' END AS status
        FROM pentest_agent.evidence_permission AS p
        LEFT JOIN pentest_agent.evidence_decision AS a
          ON (a.org_id, a.project_id, a.permission_id, a.revision) = (p.org_id, p.project_id, p.id, p.revision)
         AND a.kind = 'approve'
        LEFT JOIN pentest_agent.evidence_decision AS r
          ON (r.org_id, r.project_id, r.permission_id, r.revision) = (p.org_id, p.project_id, p.id, p.revision)
         AND r.kind = 'revoke'
        WHERE p.org_id = :org AND p.project_id = :project AND p.id = :id
          AND (CAST(:revision AS integer) IS NULL OR p.revision = :revision)
        ORDER BY p.revision DESC LIMIT 1
    """), {**_context(caller), "id": permission_id, "revision": revision}).mappings().one_or_none()
    if row is None:
        raise AccessError(404, "evidence_permission_not_found")
    return dict(row)


def _legacy(connection: Connection, source: evidence.Source) -> dict:
    row = connection.execute(text("""
        SELECT id, source_digest, jsonb_array_length(findings) AS finding_count
        FROM pentest_agent.legacy_import WHERE id = :id AND source_digest = :digest
    """), {"id": source.legacy_id, "digest": source.digest}).mappings().one_or_none()
    if row is None:
        raise AccessError(404, "evidence_not_found")
    return dict(row)


def _check_spec(connection: Connection, caller: ProjectAccess, spec: evidence.PermissionSpec) -> None:
    evidence.check_plan(spec, plan(connection, spec.plan_id), caller)
    verify_plan(connection, caller, spec.plan_id, spec.plan_hash)
    for source in spec.sources:
        if source.kind is evidence.SourceKind.LEGACY:
            _legacy(connection, source)


def request_permission(connection: Connection, caller: ProjectAccess, spec: evidence.PermissionSpec,
                       key: str, permission_id: UUID | None = None, previous: int | None = None) -> dict:
    key_digest = sha256(key.encode("ascii")).hexdigest()
    spec_data = spec.model_dump(mode="json")
    request_digest = fingerprint({"spec": spec_data, "previous": previous, "id": str(permission_id)})
    _lock(connection, caller, f"request/{caller.user_id}/{key_digest}")
    replay = connection.execute(text("""
        SELECT id, revision, request_digest
        FROM pentest_agent.evidence_permission
        WHERE org_id = :org AND project_id = :project AND requester_id = :actor AND idempotency_digest = :key
    """), {**_context(caller), "key": key_digest}).mappings().one_or_none()
    if replay is not None:
        if replay["request_digest"] != request_digest:
            raise AccessError(409, "idempotency_conflict")
        return {"id": replay["id"], "revision": replay["revision"]}
    if permission_id is not None:
        _lock(connection, caller, str(permission_id))
        current = get_permission(connection, caller, permission_id)
        if current["requester_id"] != caller.user_id:
            raise AccessError(404, "evidence_permission_not_found")
        if current["revision"] != previous:
            raise AccessError(409, "evidence_revision_changed")
    _check_spec(connection, caller, spec)
    result = {"id": permission_id or uuid4(), "revision": (previous or 0) + 1}
    connection.execute(text("""
        INSERT INTO pentest_agent.evidence_permission
            (org_id, project_id, id, revision, requester_id, plan_id, idempotency_digest, request_digest, spec)
        VALUES (:org, :project, :id, :revision, :actor, :plan, :key, :digest, CAST(:spec AS jsonb))
    """), {**_context(caller), **result, "plan": spec.plan_id, "key": key_digest,
           "digest": request_digest, "spec": json.dumps(spec_data)})
    return result


def decide(connection: Connection, caller: ProjectAccess, permission_id: UUID, revision: int,
           decision: str, reason: str) -> dict:
    _lock(connection, caller, str(permission_id))
    current = get_permission(connection, caller, permission_id)
    evidence.check_decider(caller, current["requester_id"])
    if revision != current["revision"]:
        raise AccessError(409, "evidence_revision_changed")
    if current["status"] == "revoked" or (decision == "approve" and current["status"] != "pending"):
        raise AccessError(409, "evidence_decision_conflict")
    if decision == "approve":
        spec = evidence.PermissionSpec.model_validate(current["spec"])
        if datetime.now(timezone.utc) >= spec.valid_until:
            raise AccessError(409, "evidence_permission_inactive")
        _check_spec(connection, caller, spec)
    connection.execute(text("""
        INSERT INTO pentest_agent.evidence_decision
            (org_id, project_id, permission_id, revision, kind, actor_id, reason)
        VALUES (:org, :project, :id, :revision, :kind, :actor, :reason)
    """), {**_context(caller), "id": permission_id, "revision": revision, "kind": decision, "reason": reason})
    return get_permission(connection, caller, permission_id)


def admit_source(connection: Connection, caller: ProjectAccess, permission_id: UUID, revision: int, digest: str,
                 purpose: str) -> tuple[evidence.Source, dict]:
    _lock(connection, caller, str(permission_id))
    current = get_permission(connection, caller, permission_id)
    if revision != current["revision"]:
        raise AccessError(409, "evidence_revision_changed")
    spec = evidence.PermissionSpec.model_validate(current["spec"])
    snapshot = plan(connection, spec.plan_id)
    source = evidence.authorize_use(spec, snapshot, caller, requester=current["requester_id"],
                                    approver=current["approver_id"], status=current["status"],
                                    now=datetime.now(timezone.utc), purpose=purpose, digest=digest)
    if get_disposition(connection, caller, permission_id, revision, digest) is not None:
        raise AccessError(409, "evidence_disposed")
    verify_plan(connection, caller, spec.plan_id, spec.plan_hash)
    return source, snapshot


def get_disposition(connection: Connection, caller: ProjectAccess, permission_id: UUID, revision: int,
                    digest: str) -> dict | None:
    row = connection.execute(text("""
        SELECT kind, actor_id, reason, recorded_at FROM pentest_agent.evidence_disposition
        WHERE org_id = :org AND project_id = :project AND permission_id = :id
          AND revision = :revision AND source_digest = :digest
    """), {**_context(caller), "id": permission_id, "revision": revision, "digest": digest}).mappings().one_or_none()
    return dict(row) if row else None


def withdraw_source(connection: Connection, caller: ProjectAccess, permission_id: UUID, revision: int,
                    digest: str, reason: str) -> dict:
    _lock(connection, caller, str(permission_id))
    current = get_permission(connection, caller, permission_id, revision)
    evidence.check_decider(caller, current["requester_id"])
    spec = evidence.PermissionSpec.model_validate(current["spec"])
    if not any(source.digest == digest for source in spec.sources):
        raise AccessError(404, "evidence_not_found")
    values = {**_context(caller), "id": permission_id, "revision": revision, "digest": digest, "reason": reason}
    connection.execute(text("""
        INSERT INTO pentest_agent.evidence_disposition
            (org_id, project_id, permission_id, revision, source_digest, kind, actor_id, reason)
        VALUES (:org, :project, :id, :revision, :digest, 'withdrawn', :actor, :reason)
        ON CONFLICT DO NOTHING
    """), values)
    return get_disposition(connection, caller, permission_id, revision, digest)


def upload_source(connection: Connection, caller: ProjectAccess, permission_id: UUID, revision: int,
                  digest: str) -> evidence.Source:
    source, _ = admit_source(connection, caller, permission_id, revision, digest, "offline-review")
    if source.kind not in evidence.UPLOAD_MODELS:
        raise AccessError(422, "evidence_kind_mismatch")
    return source


def _stored_projection(connection: Connection, caller: ProjectAccess, permission_id: UUID,
                       revision: int, digest: str) -> dict | None:
    row = connection.execute(text("""
        SELECT id, projection_digest, nonce, ciphertext FROM pentest_agent.evidence_projection
        WHERE org_id = :org AND project_id = :project AND permission_id = :id
          AND revision = :revision AND source_digest = :digest
    """), {**_context(caller), "id": permission_id, "revision": revision, "digest": digest}).mappings().one_or_none()
    return dict(row) if row else None


def save_upload(connection: Connection, caller: ProjectAccess, cipher: DocumentCipher,
                permission_id: UUID, revision: int, digest: str, payload: bytes) -> dict:
    source = upload_source(connection, caller, permission_id, revision, digest)
    projection = evidence.projection_bytes(evidence.project_upload(source, payload))
    prior = _stored_projection(connection, caller, permission_id, revision, digest)
    if prior is not None:
        return {"id": prior["id"], "source_digest": digest, "projection_digest": prior["projection_digest"]}
    evidence_id, projection_digest = uuid4(), sha256(projection).hexdigest()
    nonce, encrypted = cipher.encrypt_evidence(caller.org_id, caller.project_id, evidence_id,
                                                permission_id, revision, digest, projection)
    connection.execute(text("""
        INSERT INTO pentest_agent.evidence_projection
            (org_id, project_id, id, permission_id, revision, source_digest, projection_digest, nonce, ciphertext)
        VALUES (:org, :project, :id, :permission, :revision, :digest, :projection_digest, :nonce, :ciphertext)
    """), {**_context(caller), "id": evidence_id, "permission": permission_id, "revision": revision, "digest": digest,
           "projection_digest": projection_digest, "nonce": nonce, "ciphertext": encrypted})
    return {"id": evidence_id, "source_digest": digest, "projection_digest": projection_digest}


def analysis_context(connection: Connection, caller: ProjectAccess, cipher: DocumentCipher, permission_id: UUID,
                     revision: int, digest: str, *, for_local_inference: bool = False) -> dict:
    purpose = "local-inference" if for_local_inference else "offline-review"
    source, snapshot = admit_source(connection, caller, permission_id, revision, digest, purpose)
    if source.kind is evidence.SourceKind.LEGACY:
        content = evidence.project_legacy(source, _legacy(connection, source))
    else:
        stored = _stored_projection(connection, caller, permission_id, revision, digest)
        if stored is None:
            raise AccessError(404, "evidence_not_found")
        raw = cipher.decrypt_evidence(caller.org_id, caller.project_id, stored["id"], permission_id, revision, digest,
                                      stored["nonce"], stored["ciphertext"])
        if sha256(raw).hexdigest() != stored["projection_digest"]:
            raise AccessError(503, "evidence_unavailable")
        content = json.loads(raw)
    return {"scope": evidence.project_plan(snapshot, source), "source": content,
            "classification": source.classification.value, "capability": source.capability.value}
