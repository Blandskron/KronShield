"""Authenticated permission workflow and bounded offline evidence uploads."""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from pydantic import StringConstraints
from starlette.concurrency import run_in_threadpool

from adapters.api.auth import RequestAuth, RequestIdentity
from adapters.api.contract import Output
from application.access import AccessError, Action
from application.documents import DocumentCipher
from application.evidence import Digest, EvidenceModel, PermissionSpec, Revision
from infra import evidence as data
from infra.auth_store import PostgresAuthStore


IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


class PermissionRevision(EvidenceModel):
    previous_revision: Revision
    spec: PermissionSpec


class EvidenceDecisionInput(EvidenceModel):
    revision: Revision
    decision: Literal["approve", "revoke"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class PermissionReceipt(Output):
    id: UUID
    revision: Revision


class PermissionDetail(PermissionReceipt):
    requester_id: UUID
    spec: PermissionSpec
    status: Literal["pending", "approved", "revoked"]
    created_at: datetime
    approver_id: UUID | None
    approval_reason: str | None
    approved_at: datetime | None
    revoked_by: UUID | None
    revocation_reason: str | None
    revoked_at: datetime | None


class UploadReceipt(Output):
    id: UUID
    source_digest: Digest
    projection_digest: Digest


class WithdrawalInput(EvidenceModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class DispositionReceipt(Output):
    kind: Literal["withdrawn", "expired"]
    actor_id: UUID | None
    reason: str
    recorded_at: datetime


def required_idempotency_key(value: str | None) -> str:
    if value is None:
        raise AccessError(428, "idempotency_key_required")
    if not re.fullmatch(r"[!-~]{16,128}", value):
        raise AccessError(422, "invalid_idempotency_key")
    return value


def evidence_routes(auth: RequestAuth, store: PostgresAuthStore, cipher: DocumentCipher) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects/{project_id}/evidence-permissions")
    Caller = Annotated[RequestIdentity, Depends(auth.identity)]

    @router.post("", status_code=201, response_model=PermissionReceipt)
    def request_permission(identity: Caller, org_id: UUID, project_id: UUID, spec: PermissionSpec,
                           idempotency_key: IdempotencyKey = None) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.REQUEST_EVIDENCE) as (connection, caller):
            return data.request_permission(connection, caller, spec, required_idempotency_key(idempotency_key))

    @router.get("/{permission_id}", response_model=PermissionDetail)
    def get_permission(identity: Caller, org_id: UUID, project_id: UUID, permission_id: UUID,
                       revision: Annotated[int | None, Query(ge=1, le=2147483647)] = None) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, caller):
            return data.get_permission(connection, caller, permission_id, revision)

    @router.post("/{permission_id}/revisions", status_code=201, response_model=PermissionReceipt)
    def revise_permission(identity: Caller, org_id: UUID, project_id: UUID, permission_id: UUID,
                          body: PermissionRevision, idempotency_key: IdempotencyKey = None) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.REQUEST_EVIDENCE) as (connection, caller):
            return data.request_permission(connection, caller, body.spec, required_idempotency_key(idempotency_key),
                                           permission_id, body.previous_revision)

    @router.post("/{permission_id}/decisions", response_model=PermissionDetail)
    def decide_permission(identity: Caller, org_id: UUID, project_id: UUID, permission_id: UUID,
                          body: EvidenceDecisionInput) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.DECIDE_EVIDENCE) as (connection, caller):
            return data.decide(connection, caller, permission_id, body.revision, body.decision, body.reason)

    def upload_source(user: UUID, org: UUID, project: UUID, permission: UUID, revision: int, digest: str):
        with store.project(user, org, project, Action.REQUEST_EVIDENCE) as (connection, caller):
            return data.upload_source(connection, caller, permission, revision, digest)

    def persist(user: UUID, org: UUID, project: UUID, permission: UUID, revision: int, digest: str, payload: bytes):
        with store.project(user, org, project, Action.REQUEST_EVIDENCE) as (connection, caller):
            return data.save_upload(connection, caller, cipher, permission, revision, digest, payload)

    @router.put("/{permission_id}/revisions/{revision}/sources/{digest}", response_model=UploadReceipt,
                openapi_extra={"requestBody": {"required": True, "content": {"application/json":
                               {"schema": {"type": "string", "format": "binary"}}}}})
    async def upload(identity: Caller, org_id: UUID, project_id: UUID, permission_id: UUID,
                     revision: Annotated[int, Path(ge=1, le=2147483647)], digest: Digest, request: Request) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise AccessError(415, "evidence_json_required")
        args = (identity.user_id, org_id, project_id, permission_id, revision, digest)
        source = await run_in_threadpool(upload_source, *args)
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > source.size_bytes:
                raise AccessError(413, "evidence_source_too_large")
            payload.extend(chunk)
        return await run_in_threadpool(persist, *args, bytes(payload))

    disposition = "/{permission_id}/revisions/{revision}/sources/{digest}/disposition"
    SourceRevision = Annotated[int, Path(ge=1, le=2147483647)]

    @router.get(disposition, response_model=DispositionReceipt)
    def read_disposition(identity: Caller, org_id: UUID, project_id: UUID, permission_id: UUID,
                         revision: SourceRevision, digest: Digest) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, caller):
            receipt = data.get_disposition(connection, caller, permission_id, revision, digest)
            if receipt is None:
                raise AccessError(404, "evidence_disposition_not_found")
            return receipt

    @router.put(disposition, response_model=DispositionReceipt)
    def withdraw(identity: Caller, org_id: UUID, project_id: UUID, permission_id: UUID,
                 revision: SourceRevision, digest: Digest, body: WithdrawalInput) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.DECIDE_EVIDENCE) as (connection, caller):
            return data.withdraw_source(connection, caller, permission_id, revision, digest, body.reason)

    return router
