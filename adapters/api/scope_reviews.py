"""HTTP entry points for recording and verifying offline scope reviews."""

import re
from datetime import timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import HTMLResponse
from pydantic import Field, StringConstraints, field_validator

from adapters.api.auth import AUTH_HEADERS, RequestAuth, RequestIdentity
from adapters.api.contract import Assessment, Page, Plan, PlanEvents, Verification
from adapters.api.engagement_models import Contract, Name, Revision
from application.access import AccessError, Action
from infra import scope_reviews as data
from infra.auth_store import PostgresAuthStore
from reports.report_html import render_scope_review_report


class AssessmentInput(Contract):
    label: Name


class ReviewInput(Contract):
    assessment_id: UUID
    authorization_id: UUID
    authorization_revision: Revision
    target_ids: Annotated[list[UUID], Field(min_length=1, max_length=50)]
    profile_id: Literal["scope-review"] = "scope-review"

    @field_validator("target_ids")
    @classmethod
    def canonical_order(cls, target_ids: list[UUID]) -> list[UUID]:
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("Duplicate target IDs")
        return sorted(target_ids)


class VerifyInput(Contract):
    hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def scope_review_routes(auth: RequestAuth, store: PostgresAuthStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects/{project_id}")
    Caller = Annotated[RequestIdentity, Depends(auth.identity)]

    @router.get("/assessments", response_model=Page[Assessment])
    def list_assessments(identity: Caller, org_id: UUID, project_id: UUID, after: UUID | None = None,
                         limit: Annotated[int, Query(ge=1, le=100)] = 50) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return data.assessments(connection, after, limit)

    @router.get("/assessments/{assessment_id}", response_model=Assessment)
    def get_assessment(identity: Caller, org_id: UUID, project_id: UUID, assessment_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return data.assessment(connection, assessment_id)

    @router.post("/assessments", status_code=201, response_model=Assessment)
    def submit_assessment(identity: Caller, org_id: UUID, project_id: UUID, body: AssessmentInput) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_ASSESSMENTS) as (connection, caller):
            return data.create_assessment(connection, caller, body.label)

    @router.post("/plans", status_code=201, response_model=Plan)
    def submit_plan(identity: Caller, org_id: UUID, project_id: UUID, body: ReviewInput,
                    idempotency_key: Annotated[str | None, Header()] = None) -> dict:
        if idempotency_key is None:
            raise AccessError(428, "idempotency_key_required")
        if not re.fullmatch(r"[!-~]{16,128}", idempotency_key):
            raise AccessError(422, "invalid_idempotency_key")
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_ASSESSMENTS) as (connection, caller):
            return data.create_plan(connection, caller, body.model_dump(mode="json"), idempotency_key)

    @router.get("/plans/{plan_id}", response_model=Plan)
    def get_plan(identity: Caller, org_id: UUID, project_id: UUID, plan_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return data.plan(connection, plan_id)

    @router.get("/plans/{plan_id}/report", response_class=HTMLResponse)
    def report_plan(identity: Caller, org_id: UUID, project_id: UUID, plan_id: UUID) -> HTMLResponse:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            plan = data.plan(connection, plan_id)
            evaluation = data.assessment(connection, UUID(plan["assessment_id"]))
        plan["checked_at"] = plan["checked_at"].astimezone(timezone.utc).isoformat()
        return HTMLResponse(render_scope_review_report(plan, evaluation["label"]), headers={
            **AUTH_HEADERS, "Content-Disposition": f'attachment; filename="scope-review-{plan_id}.html"',
            "X-Content-Type-Options": "nosniff",
        })

    @router.get("/plans/{plan_id}/events", response_model=PlanEvents)
    def get_events(identity: Caller, org_id: UUID, project_id: UUID, plan_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return {"items": data.plan_events(connection, plan_id)}

    @router.post("/plans/{plan_id}/verify", response_model=Verification)
    def check_plan(identity: Caller, org_id: UUID, project_id: UUID, plan_id: UUID, body: VerifyInput) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, caller):
            return data.verify_plan(connection, caller, plan_id, body.hash)

    return router
