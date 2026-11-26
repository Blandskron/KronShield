"""Transactional drafts and budget receipts for offline analysis."""

import json
import re
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from application.access import AccessError, Action, ProjectAccess
from application.analyses import DEFAULT_EVENT_RULE, PROJECT_CONCURRENCY, AnalysisDraft, Usage, check_budget, pilot_budget
from application.documents import DocumentCipher
from application.scope_review import fingerprint
from domain.team_modes import TEAM_CATALOG, TeamId, TeamStep
from infra.engagements import inventory_item, organization_stop
from infra.evidence import admit_source, analysis_context, get_permission
from infra.team_selections import get_selection, lock_selection


def _scope(caller: ProjectAccess) -> dict:
    if Action.REQUEST_EVIDENCE not in caller.permissions:
        raise AccessError(403, "permission_denied")
    return {"org": caller.org_id, "project": caller.project_id, "actor": caller.user_id}


def idempotency_digest(key: str) -> str:
    if not re.fullmatch(r"[!-~]{16,128}", key):
        raise AccessError(422, "invalid_idempotency_key")
    return sha256(key.encode("ascii")).hexdigest()


def _lock(connection: Connection, caller: ProjectAccess, kind: str) -> None:
    name = f"offline-analysis/{caller.org_id}/{caller.project_id}/{kind}"
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": name})


def lock_budget(connection: Connection, caller: ProjectAccess) -> None:
    _lock(connection, caller, "budget")


def _event(connection: Connection, values: dict, kind: str, reservation: UUID | None = None) -> None:
    connection.execute(text("""
        INSERT INTO pentest_agent.analysis_event (org_id, project_id, analysis_id, sequence, kind, reservation_id)
        SELECT :org, :project, :analysis, coalesce(max(sequence), 0) + 1, :kind, :reservation
        FROM pentest_agent.analysis_event
        WHERE org_id = :org AND project_id = :project AND analysis_id = :analysis
    """), {**values, "kind": kind, "reservation": reservation})


def get_draft(connection: Connection, caller: ProjectAccess, analysis_id: UUID) -> dict:
    row = connection.execute(text("""
        SELECT id, snapshot, snapshot_digest, created_at
        FROM pentest_agent.offline_analysis
        WHERE org_id = :org AND project_id = :project AND actor_id = :actor AND id = :analysis
    """), {**_scope(caller), "analysis": analysis_id}).mappings().one_or_none()
    if row is None:
        raise AccessError(404, "analysis_not_found")
    return dict(row)


def events(connection: Connection, caller: ProjectAccess, analysis_id: UUID) -> list[dict]:
    get_draft(connection, caller, analysis_id)
    rows = connection.execute(text("""
        SELECT sequence, kind, reservation_id, created_at FROM pentest_agent.analysis_event
        WHERE org_id = :org AND project_id = :project AND analysis_id = :analysis
        ORDER BY sequence
    """), {**_scope(caller), "analysis": analysis_id}).mappings()
    return [dict(row) for row in rows]


def create_draft(connection: Connection, caller: ProjectAccess, cipher: DocumentCipher,
                 request: AnalysisDraft, key: str) -> dict:
    values = {**_scope(caller), "key": idempotency_digest(key)}
    request_digest = fingerprint({**request.model_dump(mode="json", exclude_none=True), "sources": sorted(request.sources)})
    _lock(connection, caller, f"create/{caller.user_id}/{values['key']}")
    previous = connection.execute(text("""
        SELECT id, request_digest FROM pentest_agent.offline_analysis
        WHERE org_id = :org AND project_id = :project AND actor_id = :actor AND idempotency_digest = :key
    """), values).mappings().one_or_none()
    if previous is not None:
        if previous["request_digest"] != request_digest:
            raise AccessError(409, "idempotency_conflict")
        return get_draft(connection, caller, previous["id"])

    lock_selection(connection, caller)
    if inventory_item(connection, "project", caller.project_id)["state"] != "active":
        raise AccessError(409, "project_archived")
    selected = get_selection(connection, caller)
    if selected is None or selected["version"] != request.selection_version:
        raise AccessError(409, "analysis_selection_changed")
    mode = TEAM_CATALOG.get(selected["mode_id"])
    if mode is None or (mode.version, mode.digest) != (selected["mode_version"], selected["mode_digest"]):
        raise AccessError(409, "analysis_manifest_changed")
    if request.event_rule is not None and mode.id is not TeamId.BLUE:
        raise AccessError(422, "analysis_event_rule_not_applicable")
    scenario = request.coverage_scenario
    if mode.id is TeamId.PURPLE and scenario is None:
        raise AccessError(422, "analysis_coverage_scenario_required")
    if mode.id is not TeamId.PURPLE and scenario is not None:
        raise AccessError(422, "analysis_coverage_scenario_not_applicable")
    sources = []
    for digest in sorted(request.sources):
        context = analysis_context(connection, caller, cipher, request.permission_id, request.permission_revision, digest)
        if scenario is not None and (context["scope"]["target_id"] != str(scenario.target_id)
                                     or context["capability"] != "event-review" or "events" not in context["source"]):
            raise AccessError(422, "analysis_coverage_source_mismatch")
        sources.append({"digest": digest, "context_digest": fingerprint(context),
                        "capability": context["capability"], "classification": context["classification"]})
    permission = get_permission(connection, caller, request.permission_id, request.permission_revision)
    spec = permission["spec"]
    if (spec["mode_id"], spec["mode_version"], spec["mode_digest"]) != (mode.id.value, mode.version, mode.digest):
        raise AccessError(409, "analysis_permission_mode_mismatch")

    snapshot = {
        "schema_version": 1, "status": "draft", "plan_id": spec["plan_id"], "plan_hash": spec["plan_hash"],
        "permission_id": str(request.permission_id), "permission_revision": request.permission_revision,
        "selection_version": request.selection_version, "stop_revision": organization_stop(connection, caller.org_id)["revision"],
        "manifest": mode.model_dump(mode="json"), "manifest_digest": mode.digest,
        "stage_manifests": {step.id: TEAM_CATALOG[step.team].model_dump(mode="json")
                            for step in mode.workflow if isinstance(step, TeamStep)},
        "sources": sources, "budget": pilot_budget(mode),
    }
    if mode.id is TeamId.BLUE:
        snapshot["event_rule"] = request.event_rule or DEFAULT_EVENT_RULE
    if scenario is not None:
        snapshot["coverage_scenario"] = scenario.model_dump(mode="json")
    analysis_id = uuid4()
    connection.execute(text("""
        INSERT INTO pentest_agent.offline_analysis (
            org_id, project_id, id, actor_id, plan_id, permission_id, permission_revision, selection_version,
            idempotency_digest, request_digest, snapshot_digest, snapshot
        ) VALUES (
            :org, :project, :analysis, :actor, :plan, :permission, :revision, :selection,
            :key, :request_digest, :snapshot_digest, CAST(:snapshot AS jsonb)
        )
    """), {**values, "analysis": analysis_id, "plan": spec["plan_id"], "permission": request.permission_id,
           "revision": request.permission_revision, "selection": request.selection_version, "request_digest": request_digest,
           "snapshot_digest": fingerprint(snapshot), "snapshot": json.dumps(snapshot)})
    _event(connection, {**values, "analysis": analysis_id}, "draft_recorded")
    return get_draft(connection, caller, analysis_id)


RESERVATION_FIELDS = "id, step_id, input_bytes, calls, input_tokens, output_tokens, started_at, expires_at"


def _record_settlement(connection: Connection, values: dict, reservation: UUID, usage: Usage, outcome: str) -> dict:
    row = connection.execute(text("""
        INSERT INTO pentest_agent.analysis_settlement
            (org_id, project_id, analysis_id, id, outcome, input_bytes, calls, input_tokens, output_tokens)
        VALUES (:org, :project, :analysis, :id, :outcome, :input_bytes, :calls, :input_tokens, :output_tokens)
        RETURNING id, outcome, input_bytes, calls, input_tokens, output_tokens, created_at
    """), {**values, **usage.model_dump(), "id": reservation, "outcome": outcome}).mappings().one()
    _event(connection, values, "step_settled", reservation)
    return dict(row)


def _usage(row) -> Usage:
    return Usage(**{field: row[field] for field in Usage.model_fields})


def reconcile_expired(connection: Connection, caller: ProjectAccess, analysis_id: UUID) -> int:
    values = {**_scope(caller), "analysis": analysis_id}
    get_draft(connection, caller, analysis_id)
    lock_budget(connection, caller)
    rows = connection.execute(text("""
        SELECT r.id, r.input_bytes, r.calls, r.input_tokens, r.output_tokens
        FROM pentest_agent.analysis_reservation AS r
        LEFT JOIN pentest_agent.analysis_settlement AS s
            USING (org_id, project_id, analysis_id, id)
        WHERE r.org_id = :org AND r.project_id = :project AND r.analysis_id = :analysis
          AND r.expires_at <= clock_timestamp() AND s.id IS NULL
        ORDER BY r.expires_at, r.id
    """), values).mappings().all()
    for row in rows:
        _record_settlement(connection, values, row["id"], _usage(row), "timeout")
    return len(rows)


def budget_totals(connection: Connection, values: dict):
    return connection.execute(text("""
        SELECT count(*) AS steps, min(r.started_at) AS first_at,
               count(*) FILTER (WHERE s.id IS NULL AND r.expires_at > clock_timestamp()) AS active,
               coalesce(sum(coalesce(s.input_bytes, r.input_bytes)), 0) AS input_bytes,
               coalesce(sum(coalesce(s.calls, r.calls)), 0) AS calls,
               coalesce(sum(coalesce(s.input_tokens, r.input_tokens)), 0) AS input_tokens,
               coalesce(sum(coalesce(s.output_tokens, r.output_tokens)), 0) AS output_tokens
        FROM pentest_agent.analysis_reservation AS r
        LEFT JOIN pentest_agent.analysis_settlement AS s USING (org_id, project_id, analysis_id, id)
        WHERE r.org_id = :org AND r.project_id = :project AND r.analysis_id = :analysis
    """), values).mappings().one()


def reserve_step(connection: Connection, caller: ProjectAccess, analysis_id: UUID, key: str,
                 step_id: str, usage: Usage, *, lease_seconds: int = 15) -> dict:
    """Reserve units only. The dispatcher is responsible for deciding whether work can run."""
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 120:
        raise AccessError(422, "invalid_analysis_lease")
    values = {**_scope(caller), "analysis": analysis_id, "key": idempotency_digest(key)}
    request_digest = fingerprint({"step": step_id, "usage": usage.model_dump(), "lease_seconds": lease_seconds})
    lock_budget(connection, caller)
    draft = get_draft(connection, caller, analysis_id)["snapshot"]
    previous = connection.execute(text(f"""
        SELECT {RESERVATION_FIELDS}, request_digest
        FROM pentest_agent.analysis_reservation
        WHERE org_id = :org AND project_id = :project AND analysis_id = :analysis AND idempotency_digest = :key
    """), values).mappings().one_or_none()
    if previous is not None:
        if previous["request_digest"] != request_digest:
            raise AccessError(409, "idempotency_conflict")
        return {**{name: value for name, value in previous.items() if name != "request_digest"}, "replayed": True}
    if step_id not in {step["id"] for step in draft["manifest"]["workflow"]}:
        raise AccessError(422, "unknown_analysis_step")
    purpose = "local-inference" if usage.calls else "offline-review"
    for source in draft["sources"]:
        admit_source(connection, caller, UUID(draft["permission_id"]), draft["permission_revision"],
                     source["digest"], purpose)
    if organization_stop(connection, caller.org_id)["revision"] != draft["stop_revision"]:
        raise AccessError(409, "analysis_stop_changed")

    totals = budget_totals(connection, values)
    if totals["active"]:
        raise AccessError(409, "analysis_busy")
    if connection.scalar(text("SELECT pentest_agent.active_analysis_reservations()")) >= PROJECT_CONCURRENCY:
        raise AccessError(409, "analysis_project_busy")
    budget = draft["budget"]
    check_budget(budget, totals, usage)
    now = connection.scalar(text("SELECT clock_timestamp()"))
    deadline = (totals["first_at"] or now) + timedelta(seconds=budget["seconds"])
    if now >= deadline:
        raise AccessError(409, "analysis_deadline_elapsed")
    reservation = uuid4()
    row = connection.execute(text(f"""
        INSERT INTO pentest_agent.analysis_reservation (
            org_id, project_id, analysis_id, id, idempotency_digest, request_digest, step_id,
            input_bytes, calls, input_tokens, output_tokens, started_at, expires_at
        ) VALUES (
            :org, :project, :analysis, :id, :key, :digest, :step,
            :input_bytes, :calls, :input_tokens, :output_tokens, :now, :expires
        ) RETURNING {RESERVATION_FIELDS}
    """), {**values, **usage.model_dump(), "id": reservation, "digest": request_digest, "step": step_id,
           "now": now, "expires": min(deadline, now + timedelta(seconds=lease_seconds))}).mappings().one()
    _event(connection, values, "step_reserved", reservation)
    return {**row, "replayed": False}


def settle_step(connection: Connection, caller: ProjectAccess, analysis_id: UUID, reservation_id: UUID,
                measured: Usage | None = None) -> dict:
    values = {**_scope(caller), "analysis": analysis_id, "id": reservation_id}
    get_draft(connection, caller, analysis_id)
    lock_budget(connection, caller)
    row = connection.execute(text("""
        SELECT input_bytes, calls, input_tokens, output_tokens, expires_at <= clock_timestamp() AS elapsed
        FROM pentest_agent.analysis_reservation
        WHERE org_id = :org AND project_id = :project AND analysis_id = :analysis AND id = :id
    """), values).mappings().one_or_none()
    if row is None:
        raise AccessError(404, "analysis_reservation_not_found")
    previous = connection.execute(text("""
        SELECT id, outcome, input_bytes, calls, input_tokens, output_tokens, created_at
        FROM pentest_agent.analysis_settlement
        WHERE org_id = :org AND project_id = :project AND analysis_id = :analysis AND id = :id
    """), values).mappings().one_or_none()
    if previous is not None:
        if previous["outcome"] == "measured" and measured != _usage(previous):
            raise AccessError(409, "analysis_settlement_conflict")
        return dict(previous)
    reserved = _usage(row)
    if row["elapsed"]:
        return _record_settlement(connection, values, reservation_id, reserved, "timeout")
    if measured is None:
        return _record_settlement(connection, values, reservation_id, reserved, "unknown")
    if not measured.fits(reserved):
        raise AccessError(409, "analysis_measurement_exceeds_reservation")
    return _record_settlement(connection, values, reservation_id, measured, "measured")
