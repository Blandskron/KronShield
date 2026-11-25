"""Ingest legacy files into an explicitly authorized project."""

import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from adapters.api.auth import RequestAuth, RequestIdentity
from adapters.api.contract import ImportDetail, ImportReceipt
from application.access import AccessError, Action
from application.legacy_import import LIMITS, FileFormat, parse_source
from infra.auth_store import PostgresAuthStore


def legacy_routes(auth: RequestAuth, store: PostgresAuthStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects/{project_id}/legacy-imports")
    Caller = Annotated[RequestIdentity, Depends(auth.identity)]

    def persist(identity: RequestIdentity, org_id: UUID, project_id: UUID, kind: FileFormat, raw: bytes) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_ASSESSMENTS) as (connection, caller):
            try:
                batch = parse_source(raw, kind)
            except ValueError:
                raise AccessError(422, "invalid_legacy_source") from None
            values = {"org": org_id, "project": project_id, "id": uuid4(), "actor": caller.user_id,
                      "kind": kind.value, "digest": batch.source_digest,
                      "findings": json.dumps(batch.findings, ensure_ascii=False)}
            created = connection.scalar(text("""
                INSERT INTO pentest_agent.legacy_import
                    (org_id, project_id, id, actor_id, source_format, source_digest, findings)
                VALUES (:org, :project, :id, :actor, :kind, :digest, CAST(:findings AS jsonb))
                ON CONFLICT (org_id, project_id, source_digest) DO NOTHING RETURNING id
            """), values)
            batch_id = created or connection.scalar(text("""
                SELECT id FROM pentest_agent.legacy_import WHERE source_digest = :digest
            """), values)
            return {**batch.summary(), "id": batch_id, "duplicate": created is None}

    @router.post("", status_code=201, response_model=ImportReceipt, openapi_extra={
        "requestBody": {"required": True, "content": {"application/octet-stream":
                        {"schema": {"type": "string", "format": "binary"}}}},
    })
    async def upload(request: Request, identity: Caller, org_id: UUID, project_id: UUID, format: FileFormat) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/octet-stream":
            raise AccessError(415, "binary_source_required")
        await run_in_threadpool(store.check_project, identity.user_id, org_id, project_id, Action.MANAGE_ASSESSMENTS)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > LIMITS[format]:
                raise AccessError(413, "legacy_source_too_large")
            raw.extend(chunk)
        return await run_in_threadpool(persist, identity, org_id, project_id, format, bytes(raw))

    @router.get("/{import_id}", response_model=ImportDetail)
    def get_import(identity: Caller, org_id: UUID, project_id: UUID, import_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            row = connection.execute(text("""
                SELECT id, source_format, source_digest, actor_id, created_at, findings,
                       jsonb_array_length(findings) AS finding_count
                FROM pentest_agent.legacy_import WHERE id = :id
            """), {"id": import_id}).mappings().one_or_none()
            if row is None:
                raise AccessError(404, "legacy_import_not_found")
            return {"origin": "legacy", "confidence": "unverified", **row}

    return router
