"""Revalidate evidence and persist human-reviewed offline publications."""

from datetime import timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import Connection, text

from application.access import AccessError, ProjectAccess
from application.analysis_dispatch import StepOutput, next_tool
from application.analysis_proposals import DraftProposal, ProposalReceipt
from application.documents import DocumentCipher
from application.evidence import ControlObservations, projection_bytes
from application.scope_review import fingerprint
from domain.team_modes import TeamMode
from infra.analyses import lock_budget
from infra.engagements import organization_stop
from infra.evidence import analysis_context
from reports.report_html import render_analysis_report


SCOPE = "org_id = :org AND project_id = :project AND analysis_id = :analysis"
DECISION_FIELDS = "conclusion_id, actor_id, decision, reason, decided_at"
PUBLICATION_FIELDS = "analysis_id, actor_id, report_digest, published_at"
TEMPLATE_VERSION = "offline-analysis-html-v1"


def _scope(caller: ProjectAccess, analysis_id: UUID) -> dict:
    return {"org": caller.org_id, "project": caller.project_id, "analysis": analysis_id, "actor": caller.user_id}


def _verify_sources(connection: Connection, caller: ProjectAccess, cipher: DocumentCipher,
                    permission: UUID, revision: int, sources: list[dict]) -> dict:
    contexts = {}
    for source in sources:
        context = analysis_context(connection, caller, cipher, permission, revision, source["digest"])
        if fingerprint(context) != source["context_digest"] or source["digest"] in contexts:
            raise AccessError(409, "analysis_context_changed")
        contexts[source["digest"]] = context
    return contexts


def _conclusions(snapshot: dict, outcomes: list[dict], contexts: dict) -> list[dict]:
    manifest = TeamMode.model_validate(snapshot["manifest"])
    steps = manifest.execution_order()
    completed = {item["step_id"]: item for item in outcomes if item["state"] == "completed"}
    if len(outcomes) != len(steps) or set(completed) != set(steps):
        raise AccessError(409, "analysis_review_unavailable")
    seen = set()
    decisions = []
    for step in steps:
        tool = next_tool(snapshot, seen, step)
        seen.add(step)
        outcome = completed[step]
        result = StepOutput.model_validate(outcome["output"])
        receipt = ProposalReceipt.model_validate(outcome["proposal_receipt"]) if outcome["proposal_receipt"] else None
        stage = snapshot["stage_manifests"].get(step, snapshot["manifest"])
        proof = {"tool": tool.value, "mode_id": stage["id"], "mode_version": stage["version"]}
        allowed = {digest for digest, context in contexts.items() if context["capability"] == tool.value}
        if set(result.citations) - allowed:
            raise AccessError(409, "analysis_reference_invalid")
        decisions.append({"id": f"{step}.observation", "status": result.status, "citations": sorted(result.citations),
                          "observation": None, "provenance": proof})
        if receipt and isinstance(receipt.proposal, DraftProposal):
            draft = receipt.proposal
            if (draft.observation.result == "inconclusive" or set(draft.citations) - allowed
                    or len(set(draft.citations)) != len(draft.citations)):
                raise AccessError(409, "analysis_reference_invalid")
            for digest in draft.citations:
                source = contexts[digest]["source"]
                if "observations" not in source or draft.observation not in ControlObservations.model_validate(source).observations:
                    raise AccessError(409, "analysis_reference_invalid")
            decisions.append({"id": f"{step}.draft", "status": draft.observation.result,
                              "citations": sorted(draft.citations), "observation": draft.observation.model_dump(mode="json"),
                              "provenance": {**proof, "policy_version": receipt.policy_version,
                                             "prompt_version": receipt.prompt_version,
                                             "model": receipt.model.model_dump(mode="json")}})
    return decisions


def review(connection: Connection, caller: ProjectAccess, cipher: DocumentCipher, analysis_id: UUID) -> dict:
    lock_budget(connection, caller)
    values = _scope(caller, analysis_id)
    row = connection.execute(text("""
        SELECT author_id, snapshot_digest, snapshot, cancelled, outcomes FROM pentest_agent.analysis_review_input(:analysis)
    """), values).mappings().one_or_none()
    if row is None:
        raise AccessError(404, "analysis_review_not_found")
    if row["cancelled"]:
        raise AccessError(409, "analysis_cancelled")
    snapshot = row["snapshot"]
    if fingerprint(snapshot) != row["snapshot_digest"]:
        raise AccessError(409, "analysis_snapshot_changed")
    contexts = _verify_sources(connection, caller, cipher, UUID(snapshot["permission_id"]),
                               snapshot["permission_revision"], snapshot["sources"])
    if organization_stop(connection, caller.org_id)["revision"] != snapshot["stop_revision"]:
        raise AccessError(409, "analysis_stop_changed")
    try:
        conclusions = _conclusions(snapshot, row["outcomes"], contexts)
    except (KeyError, ValueError):
        raise AccessError(409, "analysis_snapshot_invalid") from None
    decisions = connection.execute(text(f"""
        SELECT {DECISION_FIELDS} FROM pentest_agent.analysis_review_decision WHERE {SCOPE} ORDER BY conclusion_id
    """), values).mappings().all()
    publication = connection.execute(text(f"""
        SELECT {PUBLICATION_FIELDS} FROM pentest_agent.analysis_publication WHERE {SCOPE}
    """), values).mappings().one_or_none()
    return {"analysis_id": analysis_id, "author_id": row["author_id"], "snapshot_digest": row["snapshot_digest"],
            "conclusions": conclusions, "decisions": [dict(item) for item in decisions], "snapshot": snapshot,
            "publication": dict(publication) if publication is not None else None}


def decide(connection: Connection, caller: ProjectAccess, cipher: DocumentCipher, analysis_id: UUID,
           conclusion_id: str, decision: str, reason: str) -> dict:
    item = review(connection, caller, cipher, analysis_id)
    if conclusion_id not in {entry["id"] for entry in item["conclusions"]}:
        raise AccessError(404, "analysis_conclusion_not_found")
    for previous in item["decisions"]:
        if previous["conclusion_id"] == conclusion_id:
            if (previous["actor_id"], previous["decision"], previous["reason"]) != (caller.user_id, decision, reason):
                raise AccessError(409, "analysis_decision_conflict")
            return previous
    row = connection.execute(text(f"""
        INSERT INTO pentest_agent.analysis_review_decision
            (org_id, project_id, analysis_id, conclusion_id, actor_id, decision, reason)
        VALUES (:org, :project, :analysis, :conclusion, :actor, :decision, :reason)
        RETURNING {DECISION_FIELDS}
    """), {**_scope(caller, analysis_id), "conclusion": conclusion_id, "decision": decision, "reason": reason}).mappings().one()
    return dict(row)


def publish(connection: Connection, caller: ProjectAccess, cipher: DocumentCipher, analysis_id: UUID) -> dict:
    item = review(connection, caller, cipher, analysis_id)
    values = _scope(caller, analysis_id)
    if item["publication"] is not None:
        return item["publication"]
    decisions = {record["conclusion_id"]: record for record in item["decisions"]}
    if set(decisions) != {entry["id"] for entry in item["conclusions"]}:
        raise AccessError(409, "analysis_decisions_incomplete")
    snapshot = item["snapshot"]
    now = connection.scalar(text("SELECT clock_timestamp()"))
    approved = []
    for entry in item["conclusions"]:
        decision = decisions[entry["id"]]
        if decision["decision"] == "approve":
            approved.append({**entry, "reviewer_id": str(decision["actor_id"]), "reason": decision["reason"],
                             "decided_at": decision["decided_at"].astimezone(timezone.utc).isoformat()})
    publication = {
        "analysis_id": str(analysis_id), "author_id": str(item["author_id"]), "publisher_id": str(caller.user_id),
        "published_at": now.astimezone(timezone.utc).isoformat(), "template_version": TEMPLATE_VERSION,
        "plan_id": snapshot["plan_id"], "plan_hash": snapshot["plan_hash"], "snapshot_digest": item["snapshot_digest"],
        "mode_id": snapshot["manifest"]["id"], "mode_version": snapshot["manifest"]["version"],
        "selection_version": snapshot["selection_version"], "approved": approved, "rejected": len(decisions) - len(approved),
    }
    report = render_analysis_report(publication).encode("utf-8")
    row = connection.execute(text(f"""
        INSERT INTO pentest_agent.analysis_publication
            (org_id, project_id, analysis_id, actor_id, permission_id, permission_revision,
             snapshot, sources, report, report_digest, published_at)
        VALUES (:org, :project, :analysis, :actor, :permission, :revision, CAST(:snapshot AS jsonb),
                CAST(:sources AS jsonb), :report, :digest, :now) RETURNING {PUBLICATION_FIELDS}
    """), {**values, "permission": UUID(snapshot["permission_id"]), "revision": snapshot["permission_revision"],
           "snapshot": projection_bytes(publication).decode(), "sources": projection_bytes(snapshot["sources"]).decode(),
           "report": report, "digest": sha256(report).hexdigest(), "now": now}).mappings().one()
    return dict(row)


def read_report(connection: Connection, caller: ProjectAccess, cipher: DocumentCipher, analysis_id: UUID) -> tuple[bytes, str]:
    row = connection.execute(text(f"""
        SELECT permission_id, permission_revision, sources, report, report_digest
        FROM pentest_agent.analysis_publication WHERE {SCOPE}
    """), _scope(caller, analysis_id)).mappings().one_or_none()
    if row is None:
        raise AccessError(404, "analysis_publication_not_found")
    _verify_sources(connection, caller, cipher, row["permission_id"], row["permission_revision"], row["sources"])
    report = bytes(row["report"])
    if sha256(report).hexdigest() != row["report_digest"]:
        raise AccessError(503, "analysis_report_unavailable")
    return report, row["report_digest"]
