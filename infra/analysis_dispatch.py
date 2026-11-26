"""Short PostgreSQL transactions before and after an offline capability."""

import re
from dataclasses import dataclass
from functools import partial
from uuid import UUID

from sqlalchemy import Connection, text

from application.access import AccessError, Action, ProjectAccess
from application.analyses import Usage
from application.analysis_dispatch import OfflineInput, StepOutput, StepWork, next_tool, validate_output
from application.analysis_proposals import PreparedProposal, ProposalReceipt, prepare_proposal
from application.documents import DocumentCipher
from application.evidence import projection_bytes
from application.scope_review import fingerprint
from domain.team_modes import TeamMode, ToolId
from infra.analyses import budget_totals, get_draft, idempotency_digest, lock_budget, reserve_step, settle_step
from infra.auth_store import PostgresAuthStore
from infra.engagements import inventory_item, organization_stop
from infra.evidence import analysis_context


RECEIPT_FIELDS = "step_id, reservation_id, state, reason, created_at, strategy, proposal_error"
RUN_SCOPE = "org_id = :org AND project_id = :project AND analysis_id = :analysis"


def _draft(connection: Connection, caller: ProjectAccess, analysis_id: UUID) -> dict:
    row = get_draft(connection, caller, analysis_id)
    if fingerprint(row["snapshot"]) != row["snapshot_digest"]:
        raise AccessError(409, "analysis_snapshot_changed")
    return row["snapshot"]


def _outcome(connection: Connection, values: dict) -> dict | None:
    row = connection.execute(text(f"""
        SELECT {RECEIPT_FIELDS}
        FROM pentest_agent.analysis_step_outcome
        WHERE org_id = :org AND project_id = :project AND analysis_id = :analysis AND idempotency_digest = :key
    """), values).mappings().one_or_none()
    return dict(row) if row is not None else None


def _record(connection: Connection, values: dict, state: str, reason: str | None,
            reservation: UUID | None = None, output: StepOutput | None = None, *,
            proposal: ProposalReceipt | None = None) -> dict:
    row = connection.execute(text(f"""
        INSERT INTO pentest_agent.analysis_step_outcome
            (org_id, project_id, analysis_id, idempotency_digest, step_id, reservation_id, state, reason, output,
             strategy, proposal_error, proposal_receipt)
        VALUES (:org, :project, :analysis, :key, :step, :reservation, :state, :reason, CAST(:output AS jsonb),
                :strategy, :proposal_error, CAST(:proposal_receipt AS jsonb))
        RETURNING {RECEIPT_FIELDS}
    """), {**values, "reservation": reservation, "state": state, "reason": reason,
           "output": output.model_dump_json() if output is not None else None,
           "proposal_error": proposal.error if proposal else None,
           "proposal_receipt": proposal.model_dump_json() if proposal else None}).mappings().one()
    return dict(row)


def _progress(connection: Connection, values: dict, snapshot: dict) -> tuple[str, set[str]]:
    outcomes = connection.execute(text("""
        SELECT step_id, state FROM pentest_agent.analysis_step_outcome
        WHERE org_id = :org AND project_id = :project AND analysis_id = :analysis
        ORDER BY created_at DESC, idempotency_digest
    """), values).mappings().all()
    completed = {row["step_id"] for row in outcomes if row["state"] == "completed"}
    terminal = next((row["state"] for row in outcomes if row["state"] in {"blocked", "failed"}), None)
    if terminal:
        return terminal, completed
    if len(completed) == len(snapshot["manifest"]["workflow"]):
        return "awaiting_review", completed
    return ("ready" if completed else "draft"), completed


def _pending(connection: Connection, values: dict) -> dict | None:
    row = connection.execute(text("""
        SELECT r.id, r.step_id, r.idempotency_digest, r.input_bytes, r.calls, r.started_at,
               r.expires_at <= clock_timestamp() AS elapsed
        FROM pentest_agent.analysis_reservation AS r
        WHERE r.org_id = :org AND r.project_id = :project AND r.analysis_id = :analysis
          AND NOT EXISTS (
              SELECT 1 FROM pentest_agent.analysis_step_outcome AS e
              WHERE (e.org_id, e.project_id, e.analysis_id, e.idempotency_digest) =
                    (r.org_id, r.project_id, r.analysis_id, r.idempotency_digest)
          )
        ORDER BY r.started_at, r.id LIMIT 1
    """), values).mappings().one_or_none()
    return dict(row) if row is not None else None


def _cancelled_at(connection: Connection, values: dict):
    return connection.scalar(text(f"SELECT cancelled_at FROM pentest_agent.analysis_cancellation WHERE {RUN_SCOPE}"), values)


def _strategy(pending: dict) -> str:
    return "assisted" if pending["calls"] else "deterministic"


def _pending_values(values: dict, pending: dict) -> dict:
    return {**values, "key": pending["idempotency_digest"], "step": pending["step_id"], "strategy": _strategy(pending)}


def _recover(connection: Connection, caller: ProjectAccess, values: dict, pending: dict) -> dict:
    settle_step(connection, caller, values["analysis"], pending["id"])
    return _record(connection, _pending_values(values, pending), "failed", "analysis_step_timeout", pending["id"])


@dataclass(frozen=True)
class AssistedWork(StepWork):
    prepared: PreparedProposal


@dataclass(frozen=True)
class PostgresDispatch:
    store: PostgresAuthStore
    cipher: DocumentCipher
    org_id: UUID
    project_id: UUID
    actor_id: UUID

    def state(self, analysis_id: UUID) -> str:
        return self.detail(analysis_id)["state"]

    def detail(self, analysis_id: UUID) -> dict:
        values = {"org": self.org_id, "project": self.project_id, "analysis": analysis_id}
        with self.store.project(self.actor_id, self.org_id, self.project_id, Action.REQUEST_EVIDENCE) as (connection, caller):
            lock_budget(connection, caller)
            row = get_draft(connection, caller, analysis_id)
            snapshot = row["snapshot"]
            if fingerprint(snapshot) != row["snapshot_digest"]:
                raise AccessError(409, "analysis_snapshot_changed")
            pending = _pending(connection, values)
            if pending is not None and pending["elapsed"]:
                _recover(connection, caller, values, pending)
                pending = None
            state, completed = _progress(connection, values, snapshot)
            cancelled = _cancelled_at(connection, values)
            if cancelled is not None:
                state = "cancelled"
            elif state == "awaiting_review" and connection.scalar(
                text(f"SELECT true FROM pentest_agent.analysis_publication WHERE {RUN_SCOPE}"), values
            ):
                state = "published"
            elif pending is not None:
                state = "processing"
            manifest = TeamMode.model_validate(snapshot["manifest"])
            next_step = next((step for step in manifest.execution_order() if step not in completed), None)
            steps = connection.execute(text(f"""
                SELECT {RECEIPT_FIELDS} FROM pentest_agent.analysis_step_outcome WHERE {RUN_SCOPE}
                ORDER BY created_at, idempotency_digest
            """), values).mappings().all()
            receipts = [dict(step) for step in steps]
            if pending is not None:
                receipts.append(self._processing(pending))
            return {"id": row["id"], "snapshot_digest": row["snapshot_digest"], "created_at": row["created_at"],
                    "plan_id": snapshot["plan_id"], "plan_hash": snapshot["plan_hash"],
                    "mode_id": manifest.id, "mode_version": manifest.version,
                    "selection_version": snapshot["selection_version"], "state": state, "cancelled_at": cancelled,
                    "next_step": next_step if state in {"draft", "ready", "processing"} else None,
                    "steps": receipts}

    def cancel(self, analysis_id: UUID) -> dict:
        values = {"org": self.org_id, "project": self.project_id, "analysis": analysis_id}
        with self.store.project(self.actor_id, self.org_id, self.project_id, Action.REQUEST_EVIDENCE) as (connection, caller):
            lock_budget(connection, caller)
            _draft(connection, caller, analysis_id)
            cancelled = _cancelled_at(connection, values)
            if cancelled is None:
                if connection.scalar(text(f"SELECT true FROM pentest_agent.analysis_publication WHERE {RUN_SCOPE}"), values):
                    raise AccessError(409, "analysis_already_published")
                pending = _pending(connection, values)
                if pending is not None:
                    if pending["elapsed"]:
                        _recover(connection, caller, values, pending)
                    else:
                        settle_step(connection, caller, analysis_id, pending["id"])
                        _record(connection, _pending_values(values, pending), "blocked", "analysis_cancelled", pending["id"])
                cancelled = connection.scalar(text("""
                    INSERT INTO pentest_agent.analysis_cancellation (org_id, project_id, analysis_id)
                    VALUES (:org, :project, :analysis) RETURNING cancelled_at
                """), values)
            return {"id": analysis_id, "state": "cancelled", "cancelled_at": cancelled}

    @staticmethod
    def _processing(pending: dict) -> dict:
        return {"step_id": pending["step_id"], "reservation_id": pending["id"], "state": "processing",
                "strategy": _strategy(pending), "reason": None, "proposal_error": None, "created_at": pending["started_at"]}

    def _values(self, analysis_id: UUID, step_id: str, key: str) -> dict:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", step_id):
            raise AccessError(422, "unknown_analysis_step")
        return {"org": self.org_id, "project": self.project_id, "analysis": analysis_id,
                "step": step_id, "key": idempotency_digest(key)}

    def _inputs(self, connection: Connection, caller: ProjectAccess, snapshot: dict,
                tool: ToolId, *, for_local_inference: bool = False) -> tuple[OfflineInput, ...]:
        if inventory_item(connection, "project", caller.project_id)["state"] != "active":
            raise AccessError(409, "project_archived")
        inputs = []
        for source in snapshot["sources"]:
            # Revalidate all sources, including dependencies whose outputs may be consumed later.
            context = analysis_context(connection, caller, self.cipher, UUID(snapshot["permission_id"]),
                                       snapshot["permission_revision"], source["digest"],
                                       for_local_inference=for_local_inference)
            if fingerprint(context) != source["context_digest"]:
                raise AccessError(409, "analysis_context_changed")
            if context["capability"] == tool:
                inputs.append(OfflineInput(digest=source["digest"], scope=context["scope"], source=context["source"]))
        if organization_stop(connection, caller.org_id)["revision"] != snapshot["stop_revision"]:
            raise AccessError(409, "analysis_stop_changed")
        if not inputs:
            raise AccessError(409, "analysis_evidence_missing")
        return tuple(inputs)

    def start(self, analysis_id: UUID, step_id: str, key: str, available: frozenset[ToolId], *,
              assisted: bool = False, inference_available: bool = False) -> StepWork | dict:
        values = {**self._values(analysis_id, step_id, key), "strategy": "assisted" if assisted else "deterministic"}
        with self.store.project(self.actor_id, self.org_id, self.project_id, Action.REQUEST_EVIDENCE) as (connection, caller):
            lock_budget(connection, caller)
            snapshot = _draft(connection, caller, analysis_id)
            recorded = _outcome(connection, values)
            if recorded is not None:
                if (recorded["step_id"], recorded["strategy"]) != (step_id, values["strategy"]):
                    raise AccessError(409, "idempotency_conflict")
                return recorded
            if _cancelled_at(connection, values) is not None:
                raise AccessError(409, "analysis_cancelled")
            pending = _pending(connection, values)
            if pending is not None:
                same_key = pending["idempotency_digest"] == values["key"]
                if same_key and (pending["step_id"], _strategy(pending)) != (step_id, values["strategy"]):
                    raise AccessError(409, "idempotency_conflict")
                if pending["elapsed"]:
                    if not same_key:
                        raise AccessError(409, "analysis_step_timeout")
                    return _recover(connection, caller, values, pending)
                if same_key:
                    return self._processing(pending)
                raise AccessError(409, "analysis_busy")
            state, completed = _progress(connection, values, snapshot)
            if state not in {"draft", "ready"}:
                raise AccessError(409, "analysis_transition_invalid")
            tool = next_tool(snapshot, completed, step_id)
            if assisted and tool in available and not inference_available:
                raise AccessError(503, "proposal_dependency_missing")
            try:
                if tool not in available:
                    raise AccessError(409, "analysis_capability_unavailable")
                inputs = self._inputs(connection, caller, snapshot, tool)
                input_bytes = len(projection_bytes([item.model_dump(mode="json") for item in inputs]))
                prepared = None
                usage = Usage(input_bytes=input_bytes)
                if assisted:
                    loader = partial(analysis_context, connection, caller, self.cipher)
                    prepared = prepare_proposal(snapshot, completed, step_id, loader,
                                                budget_totals(connection, values), input_token_limit=1536,
                                                output_token_limit=192)
                    usage = Usage(**{**prepared.allowance.model_dump(),
                                     "input_bytes": input_bytes + prepared.allowance.input_bytes})
                reservation = reserve_step(connection, caller, analysis_id, key, step_id, usage)
            except AccessError as error:
                if error.code in {"analysis_busy", "analysis_project_busy"}:
                    raise
                return _record(connection, values, "blocked", error.code)
            except ValueError:
                return _record(connection, values, "failed", "analysis_snapshot_invalid")
            if prepared is not None:
                return AssistedWork(reservation["id"], tool, inputs, prepared)
            return StepWork(reservation["id"], tool, inputs)

    def finish(self, analysis_id: UUID, step_id: str, key: str, reservation_id: UUID, *,
               output: StepOutput | None, failure: str | None, proposal: ProposalReceipt | None = None) -> dict:
        values = self._values(analysis_id, step_id, key)
        with self.store.project(self.actor_id, self.org_id, self.project_id, Action.REQUEST_EVIDENCE,
                                guard_membership=True) as (connection, caller):
            lock_budget(connection, caller)
            snapshot = _draft(connection, caller, analysis_id)
            recorded = _outcome(connection, values)
            if recorded is not None:
                if (recorded["step_id"], recorded["reservation_id"]) != (step_id, reservation_id):
                    raise AccessError(409, "idempotency_conflict")
                return recorded
            pending = _pending(connection, values)
            if (pending is None or (pending["id"], pending["step_id"], pending["idempotency_digest"])
                    != (reservation_id, step_id, values["key"])):
                raise AccessError(409, "analysis_reservation_mismatch")
            values["strategy"] = _strategy(pending)
            if pending["elapsed"]:
                return _recover(connection, caller, values, pending)
            try:
                _, completed = _progress(connection, values, snapshot)
                tool = next_tool(snapshot, completed, step_id)
                inputs = self._inputs(connection, caller, snapshot, tool, for_local_inference=bool(pending["calls"]))
            except AccessError as error:
                settle_step(connection, caller, analysis_id, reservation_id)
                return _record(connection, values, "blocked", error.code, reservation_id)
            except ValueError:
                settle_step(connection, caller, analysis_id, reservation_id)
                return _record(connection, values, "failed", "analysis_snapshot_invalid", reservation_id)
            if output is not None:
                try:
                    output = validate_output(output, inputs)
                except ValueError:
                    failure = "analysis_output_invalid"
            measured = None
            if proposal is not None:
                measured = Usage(**{**proposal.usage.model_dump(), "input_bytes": pending["input_bytes"]})
            elif not pending["calls"]:
                measured = Usage(input_bytes=pending["input_bytes"])
            settled = settle_step(connection, caller, analysis_id, reservation_id, measured)
            if settled["outcome"] == "timeout":
                return _record(connection, values, "failed", "analysis_step_timeout", reservation_id)
            if failure or output is None:
                reason = failure if failure in {"analysis_output_invalid", "analysis_handler_failed"} else "analysis_output_invalid"
                return _record(connection, values, "failed", reason, reservation_id)
            if pending["calls"] and proposal is None:
                return _record(connection, values, "failed", "proposal_provider_failed", reservation_id)
            return _record(connection, values, "completed", None, reservation_id, output, proposal=proposal)
