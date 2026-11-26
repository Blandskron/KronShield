"""Owner-scoped lifecycle for defensive offline analyses."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import StringConstraints

from adapters.api.auth import AUTH_HEADERS, RequestAuth, RequestIdentity
from adapters.api.contract import Output
from adapters.api.evidence import IdempotencyKey, required_idempotency_key
from application.access import Action
from application.analyses import AnalysisDraft
from application.analysis_dispatch import EventTriage, OfflineInput, StepOutput, dispatch_step, event_review
from application.analysis_proposals import ModelVersion, ProposalProvider, generate_proposal
from application.documents import DocumentCipher
from application.evidence import ControlObservation, Digest, EvidenceModel, Revision
from domain.team_modes import TeamId, ToolId
from infra.analyses import create_draft
from infra.analysis_dispatch import AssistedWork, PostgresDispatch
from infra.auth_store import PostgresAuthStore
from infra import analysis_reviews


Strategy = Literal["deterministic", "assisted"]
Inference = tuple[ModelVersion, ProposalProvider]


def review_scope(inputs: tuple[OfflineInput, ...]) -> StepOutput:
    return StepOutput(status="observed", citations=tuple(item.digest for item in inputs))


DETERMINISTIC = {ToolId.SCOPE_RECORD_REVIEW: review_scope, ToolId.EVENT_REVIEW: event_review}


class AnalysisAdvance(EvidenceModel):
    strategy: Strategy = "deterministic"


class AnalysisCreated(Output):
    id: UUID
    snapshot_digest: Digest
    created_at: datetime


class AnalysisStepReceipt(Output):
    step_id: str
    reservation_id: UUID | None
    state: Literal["processing", "completed", "blocked", "failed"]
    reason: str | None
    created_at: datetime
    strategy: Strategy
    proposal_error: str | None


class AnalysisDetail(AnalysisCreated):
    plan_id: UUID
    plan_hash: Digest
    mode_id: TeamId
    mode_version: Revision
    selection_version: int
    state: Literal["draft", "ready", "processing", "awaiting_review", "published", "cancelled", "blocked", "failed"]
    cancelled_at: datetime | None
    next_step: str | None
    steps: list[AnalysisStepReceipt]


class AnalysisCancellation(Output):
    id: UUID
    state: Literal["cancelled"]
    cancelled_at: datetime


ConclusionId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}[.](observation|draft)$")]
ReviewDecision = Literal["approve", "reject"]


class AnalysisDecisionInput(EvidenceModel):
    decision: ReviewDecision
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500, pattern=r"^[^\x00]+$")]


class AnalysisDecision(Output):
    conclusion_id: ConclusionId
    actor_id: UUID
    decision: ReviewDecision
    reason: str
    decided_at: datetime


class AnalysisProvenance(Output):
    tool: ToolId
    mode_id: TeamId
    mode_version: Revision
    policy_version: str | None = None
    prompt_version: str | None = None
    model: ModelVersion | None = None


class AnalysisConclusion(Output):
    id: ConclusionId
    status: Literal["observed", "missing", "inconclusive"]
    citations: list[Digest]
    observation: ControlObservation | None
    triage: EventTriage | None = None
    provenance: AnalysisProvenance


class AnalysisPublication(Output):
    analysis_id: UUID
    actor_id: UUID
    report_digest: Digest
    published_at: datetime


class AnalysisReview(Output):
    analysis_id: UUID
    author_id: UUID
    snapshot_digest: Digest
    conclusions: list[AnalysisConclusion]
    decisions: list[AnalysisDecision]
    publication: AnalysisPublication | None = None


def analysis_routes(auth: RequestAuth, store: PostgresAuthStore, cipher: DocumentCipher,
                    inference: Inference | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects/{project_id}/analyses")
    Caller = Annotated[RequestIdentity, Depends(auth.identity)]

    @router.post("", status_code=201, response_model=AnalysisCreated)
    def create_analysis(identity: Caller, org_id: UUID, project_id: UUID, body: AnalysisDraft,
                        idempotency_key: IdempotencyKey = None) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.REQUEST_EVIDENCE) as (connection, caller):
            row = create_draft(connection, caller, cipher, body, required_idempotency_key(idempotency_key))
        return {name: row[name] for name in AnalysisCreated.model_fields}

    @router.get("/{analysis_id}", response_model=AnalysisDetail)
    def read_analysis(identity: Caller, org_id: UUID, project_id: UUID, analysis_id: UUID) -> dict:
        return PostgresDispatch(store, cipher, org_id, project_id, identity.user_id).detail(analysis_id)

    @router.post("/{analysis_id}/steps/{step_id}", response_model=AnalysisStepReceipt)
    def advance_analysis(identity: Caller, org_id: UUID, project_id: UUID, analysis_id: UUID, step_id: str,
                         body: AnalysisAdvance, idempotency_key: IdempotencyKey = None) -> dict:
        dispatch = PostgresDispatch(store, cipher, org_id, project_id, identity.user_id)
        key = required_idempotency_key(idempotency_key)
        if body.strategy == "deterministic":
            return dispatch_step(dispatch, DETERMINISTIC, analysis_id, step_id, key)
        work = dispatch.start(analysis_id, step_id, key, frozenset(DETERMINISTIC), assisted=True,
                              inference_available=inference is not None)
        if isinstance(work, dict):
            return work
        proposal = generate_proposal(work.prepared, *inference) if isinstance(work, AssistedWork) and inference else None
        output = review_scope(work.inputs)
        return dispatch.finish(analysis_id, step_id, key, work.reservation_id, output=output, failure=None,
                               proposal=proposal)

    @router.put("/{analysis_id}/cancellation", response_model=AnalysisCancellation)
    def cancel_analysis(identity: Caller, org_id: UUID, project_id: UUID, analysis_id: UUID) -> dict:
        return PostgresDispatch(store, cipher, org_id, project_id, identity.user_id).cancel(analysis_id)

    @router.get("/{analysis_id}/review", response_model=AnalysisReview)
    def review_analysis(identity: Caller, org_id: UUID, project_id: UUID, analysis_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.PUBLISH_ANALYSIS,
                           guard_membership=True) as (connection, caller):
            item = analysis_reviews.review(connection, caller, cipher, analysis_id)
        return {key: item[key] for key in AnalysisReview.model_fields}

    @router.put("/{analysis_id}/review/decisions/{conclusion_id}", response_model=AnalysisDecision)
    def decide_analysis(identity: Caller, org_id: UUID, project_id: UUID, analysis_id: UUID,
                        conclusion_id: ConclusionId, body: AnalysisDecisionInput) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.PUBLISH_ANALYSIS,
                           guard_membership=True) as (connection, caller):
            return analysis_reviews.decide(connection, caller, cipher, analysis_id, conclusion_id, body.decision, body.reason)

    @router.put("/{analysis_id}/publication", response_model=AnalysisPublication)
    def publish_analysis(identity: Caller, org_id: UUID, project_id: UUID, analysis_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.PUBLISH_ANALYSIS,
                           guard_membership=True) as (connection, caller):
            return analysis_reviews.publish(connection, caller, cipher, analysis_id)

    @router.get("/{analysis_id}/publication/report", response_class=HTMLResponse)
    def download_analysis(identity: Caller, org_id: UUID, project_id: UUID, analysis_id: UUID) -> HTMLResponse:
        with store.project(identity.user_id, org_id, project_id, Action.READ, guard_membership=True) as (connection, caller):
            report, digest = analysis_reviews.read_report(connection, caller, cipher, analysis_id)
        return HTMLResponse(report, headers={
            **AUTH_HEADERS, "Content-Disposition": f'attachment; filename="analysis-{analysis_id}.html"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff", "ETag": f'"{digest}"',
        })

    return router
