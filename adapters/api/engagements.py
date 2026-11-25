"""Authenticated inventory and authorization endpoints."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from adapters.api.auth import AUTH_HEADERS, RequestAuth, RequestIdentity
from adapters.api.contract import Authorization, Customer, Document, Organization, OrganizationStop, Page, Project, Target
from adapters.api.engagement_models import (
    AuthorizationInput, AuthorizationRevision, CustomerInput, CustomerPatch, DecisionInput,
    OrganizationInput, OrganizationPatch, OrganizationStopInput, ProjectInput, ProjectPatch, TargetInput, TargetPatch,
)
from application.access import AccessError, Action
from application.documents import MAX_DOCUMENT_SIZE, DocumentCipher
from infra import engagements as data
from infra.auth_store import PostgresAuthStore
from infra.tenancy import tenant_transaction


PageSize = Annotated[int, Query(ge=1, le=100)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
PROJECT = "/projects/{project_id}"


def _version(header: str | None, *, allow_initial: bool = False) -> int:
    if header is None:
        raise AccessError(428, "if_match_required")
    if allow_initial and header == '"0"':
        return 0
    if not re.fullmatch(r'"[1-9][0-9]{0,17}"', header):
        raise AccessError(400, "invalid_if_match")
    return int(header[1:-1])


def _target_values(target: TargetInput) -> dict:
    try:
        return target.storage_values()
    except ValueError:
        raise AccessError(422, "invalid_target") from None


def _authorization_values(body: AuthorizationInput) -> dict:
    try:
        rules = [rule.snapshot() for rule in body.scope_rules]
    except ValueError:
        raise AccessError(422, "invalid_scope_rule") from None
    return {"document_evidence_id": body.document_evidence_id, "delegator_id": body.delegator_id,
            "valid_from": body.valid_from, "valid_until": body.valid_until,
            "scope_rules": rules, "limits": body.limits.model_dump(mode="json")}


def engagement_routes(auth: RequestAuth, store: PostgresAuthStore, cipher: DocumentCipher) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    Caller = Annotated[RequestIdentity, Depends(auth.identity)]

    @contextmanager
    def organization(identity: RequestIdentity, org_id: UUID, *, admin: bool = False,
                     allow_suspended: bool = False) -> Iterator:
        with tenant_transaction(store.engine, user_id=identity.user_id, org_id=org_id) as connection:
            org = data.inventory_item(connection, "organization", org_id)
            if admin and data.organization_role(connection, identity.user_id, org_id) != "org_admin":
                raise AccessError(403, "permission_denied")
            if org["state"] != "active" and not allow_suspended:
                raise AccessError(404, "organization_not_found")
            yield connection, org

    @router.get("/organizations", response_model=Page[Organization])
    def list_organizations(identity: Caller, after: UUID | None = None, limit: PageSize = 50) -> dict:
        with tenant_transaction(store.engine, user_id=identity.user_id, org_id=None) as connection:
            return data.inventory_page(connection, "organization", after, limit)

    @router.post("/organizations", status_code=201, response_model=Organization)
    def create_organization(identity: Caller, body: OrganizationInput) -> dict:
        org_id = uuid4()
        with tenant_transaction(store.engine, user_id=identity.user_id, org_id=org_id) as connection:
            if not data.is_platform_admin(connection, identity.user_id):
                raise AccessError(403, "permission_denied")
            if identity.user_id == body.admin_id:
                raise AccessError(422, "separate_organization_admin_required")
            data.insert_inventory(connection, "organization", {"id": org_id, "slug": body.slug})
            data.insert_inventory(connection, "organization_membership",
                                  {"org_id": org_id, "user_id": body.admin_id, "role_id": "org_admin"})
        return {"id": org_id, "slug": body.slug, "state": "active", "version": 1}

    @router.get("/organizations/{org_id}", response_model=Organization)
    def get_organization(identity: Caller, org_id: UUID) -> dict:
        with organization(identity, org_id, allow_suspended=True) as (_, org):
            return org

    @router.get("/organizations/{org_id}/stop", response_model=OrganizationStop)
    def get_stop(identity: Caller, org_id: UUID, response: Response) -> dict:
        with organization(identity, org_id, admin=True) as (connection, _):
            status = data.organization_stop(connection, org_id)
            response.headers["ETag"] = f'"{status["revision"]}"'
            return status

    @router.put("/organizations/{org_id}/stop", response_model=OrganizationStop)
    def put_stop(identity: Caller, org_id: UUID, body: OrganizationStopInput,
                 response: Response, if_match: IfMatch = None) -> dict:
        with organization(identity, org_id, admin=True) as (connection, _):
            status = data.update_organization_stop(connection, _version(if_match, allow_initial=True),
                                                     body.enabled, body.reason)
            response.headers["ETag"] = f'"{status["revision"]}"'
            return status

    @router.patch("/organizations/{org_id}", response_model=Organization)
    def update_organization(identity: Caller, org_id: UUID, body: OrganizationPatch,
                            if_match: IfMatch = None) -> dict:
        with organization(identity, org_id, admin=True, allow_suspended=True) as (connection, _):
            return data.change_inventory(connection, "organization", org_id, _version(if_match),
                                         body.model_dump(exclude_unset=True))

    @router.delete("/organizations/{org_id}", status_code=204, response_class=Response)
    def suspend_organization(identity: Caller, org_id: UUID, if_match: IfMatch = None) -> Response:
        with organization(identity, org_id, admin=True, allow_suspended=True) as (connection, _):
            data.change_inventory(connection, "organization", org_id, _version(if_match), {"state": "suspended"})
        return Response(status_code=204)

    @router.get("/customers", response_model=Page[Customer])
    def list_customers(identity: Caller, org_id: UUID, after: UUID | None = None, limit: PageSize = 50) -> dict:
        with organization(identity, org_id) as (connection, _):
            return data.inventory_page(connection, "customer", after, limit)

    @router.post("/customers", status_code=201, response_model=Customer)
    def create_customer(identity: Caller, org_id: UUID, body: CustomerInput) -> dict:
        customer_id = uuid4()
        with organization(identity, org_id, admin=True) as (connection, _):
            data.insert_inventory(connection, "customer", {**body.model_dump(), "org_id": org_id, "id": customer_id})
            return data.inventory_item(connection, "customer", customer_id)

    @router.get("/customers/{customer_id}", response_model=Customer)
    def get_customer(identity: Caller, org_id: UUID, customer_id: UUID) -> dict:
        with organization(identity, org_id) as (connection, _):
            return data.inventory_item(connection, "customer", customer_id)

    @router.patch("/customers/{customer_id}", response_model=Customer)
    def update_customer(identity: Caller, org_id: UUID, customer_id: UUID, body: CustomerPatch,
                        if_match: IfMatch = None) -> dict:
        with organization(identity, org_id, admin=True) as (connection, _):
            return data.change_inventory(connection, "customer", customer_id, _version(if_match),
                                         body.model_dump(exclude_unset=True))

    @router.delete("/customers/{customer_id}", status_code=204, response_class=Response)
    def delete_customer(identity: Caller, org_id: UUID, customer_id: UUID, if_match: IfMatch = None) -> Response:
        with organization(identity, org_id, admin=True) as (connection, _):
            data.remove_inventory(connection, "customer", customer_id, _version(if_match))
        return Response(status_code=204)

    @router.get("/projects", response_model=Page[Project])
    def list_projects(identity: Caller, org_id: UUID, after: UUID | None = None, limit: PageSize = 50) -> dict:
        with organization(identity, org_id) as (connection, _):
            return data.inventory_page(connection, "project", after, limit)

    @router.post("/projects", status_code=201, response_model=Project)
    def create_project(identity: Caller, org_id: UUID, body: ProjectInput) -> dict:
        project_id = uuid4()
        with tenant_transaction(store.engine, user_id=identity.user_id, org_id=org_id, project_id=project_id) as conn:
            org = data.inventory_item(conn, "organization", org_id)
            if org["state"] != "active":
                raise AccessError(404, "organization_not_found")
            if data.organization_role(conn, identity.user_id, org_id) != "org_admin":
                raise AccessError(403, "permission_denied")
            data.inventory_item(conn, "customer", body.customer_id)
            data.insert_inventory(conn, "project", {**body.model_dump(), "org_id": org_id, "id": project_id})
            data.insert_inventory(conn, "project_membership",
                                  {"org_id": org_id, "project_id": project_id,
                                   "user_id": identity.user_id, "role_id": "project_admin"})
            return data.inventory_item(conn, "project", project_id)

    @router.get(PROJECT, response_model=Project)
    def get_project(identity: Caller, org_id: UUID, project_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return data.inventory_item(connection, "project", project_id)

    @router.patch(PROJECT, response_model=Project)
    def update_project(identity: Caller, org_id: UUID, project_id: UUID, body: ProjectPatch,
                       if_match: IfMatch = None) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_PROJECT) as (connection, _):
            return data.change_inventory(connection, "project", project_id, _version(if_match),
                                         body.model_dump(exclude_unset=True))

    @router.delete(PROJECT, status_code=204, response_class=Response)
    def archive_project(identity: Caller, org_id: UUID, project_id: UUID, if_match: IfMatch = None) -> Response:
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_PROJECT) as (connection, _):
            data.change_inventory(connection, "project", project_id, _version(if_match), {"state": "archived"})
        return Response(status_code=204)

    @router.get(PROJECT + "/targets", response_model=Page[Target])
    def list_targets(identity: Caller, org_id: UUID, project_id: UUID,
                     after: UUID | None = None, limit: PageSize = 50) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return data.inventory_page(connection, "target", after, limit)

    @router.get(PROJECT + "/targets/{target_id}", response_model=Target)
    def get_target(identity: Caller, org_id: UUID, project_id: UUID, target_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return data.inventory_item(connection, "target", target_id)

    @router.post(PROJECT + "/targets", status_code=201, response_model=Target)
    def create_target(identity: Caller, org_id: UUID, project_id: UUID, body: TargetInput) -> dict:
        target_id = uuid4()
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_TARGETS) as (connection, _):
            data.insert_inventory(connection, "target",
                                  {**_target_values(body), "id": target_id, "org_id": org_id, "project_id": project_id})
            return data.inventory_item(connection, "target", target_id)

    @router.patch(PROJECT + "/targets/{target_id}", response_model=Target)
    def update_target(identity: Caller, org_id: UUID, project_id: UUID, target_id: UUID,
                      body: TargetPatch, if_match: IfMatch = None) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_TARGETS) as (connection, _):
            changes = body.model_dump(exclude_unset=True)
            expected = _version(if_match)
            if changes.keys() == {"slug"}:
                return data.change_inventory(connection, "target", target_id, expected, changes)
            previous = data.inventory_item(connection, "target", target_id)
            values = {field: previous[field] for field in ("slug", "environment", "attribution", "third_party_id")}
            values["address"] = previous["canonical_address"]
            values.update(changes)
            return data.change_inventory(connection, "target", target_id, expected,
                                         _target_values(TargetInput(**values)))

    @router.delete(PROJECT + "/targets/{target_id}", status_code=204, response_class=Response)
    def delete_target(identity: Caller, org_id: UUID, project_id: UUID, target_id: UUID,
                      if_match: IfMatch = None) -> Response:
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_TARGETS) as (connection, _):
            data.remove_inventory(connection, "target", target_id, _version(if_match))
        return Response(status_code=204)

    def _store_document(identity: RequestIdentity, org_id: UUID, project_id: UUID, payload: bytes) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.REQUEST_AUTHORIZATION) as (connection, _):
            document_id = uuid4()
            digest, nonce, ciphertext = cipher.encrypt(org_id, project_id, document_id, payload)
            return data.store_document(connection, {"org": org_id, "project": project_id, "id": document_id,
                                                    "actor": identity.user_id, "digest": digest,
                                                    "nonce": nonce, "ciphertext": ciphertext})

    @router.post(PROJECT + "/authorization-documents", status_code=201, response_model=Document,
                 openapi_extra={"requestBody": {"required": True, "content": {"application/pdf":
                                {"schema": {"type": "string", "format": "binary"}}}}})
    async def upload_document(identity: Caller, request: Request, org_id: UUID, project_id: UUID) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/pdf":
            raise AccessError(415, "pdf_required")
        await run_in_threadpool(store.check_project, identity.user_id, org_id, project_id, Action.REQUEST_AUTHORIZATION)
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > MAX_DOCUMENT_SIZE:
                raise AccessError(413, "document_too_large")
            payload.extend(chunk)
        return await run_in_threadpool(_store_document, identity, org_id, project_id, bytes(payload))

    @router.get(PROJECT + "/authorization-documents/{document_id}", response_class=Response)
    def download_document(identity: Caller, org_id: UUID, project_id: UUID, document_id: UUID) -> Response:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            row = data.document(connection, document_id, content=True)
            payload = cipher.decrypt(org_id, project_id, document_id, row["digest"], row["nonce"], row["ciphertext"])
        return Response(payload, media_type="application/pdf", headers={
            **AUTH_HEADERS, "Content-Disposition": f'attachment; filename="{document_id}.pdf"',
            "X-Content-Type-Options": "nosniff",
        })

    @router.get(PROJECT + "/authorizations", response_model=Page[Authorization])
    def list_authorizations(identity: Caller, org_id: UUID, project_id: UUID,
                            after: UUID | None = None, limit: PageSize = 50) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return data.authorizations(connection, after, limit)

    @router.get(PROJECT + "/authorizations/{authorization_id}", response_model=Authorization)
    def get_authorization(identity: Caller, org_id: UUID, project_id: UUID, authorization_id: UUID,
                          revision: Annotated[int | None, Query(ge=1, le=2147483647)] = None) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, _):
            return data.authorization(connection, authorization_id, revision)

    @router.post(PROJECT + "/authorizations", status_code=201, response_model=Authorization)
    def create_authorization(identity: Caller, org_id: UUID, project_id: UUID, body: AuthorizationInput) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.REQUEST_AUTHORIZATION) as (connection, _):
            return data.save_authorization(connection, org_id, project_id, identity.user_id,
                                           _authorization_values(body))

    @router.post(PROJECT + "/authorizations/{authorization_id}/revisions", status_code=201, response_model=Authorization)
    def revise_authorization(identity: Caller, org_id: UUID, project_id: UUID, authorization_id: UUID,
                             body: AuthorizationRevision) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.REQUEST_AUTHORIZATION) as (connection, _):
            return data.save_authorization(connection, org_id, project_id, identity.user_id,
                                           _authorization_values(body), authorization_id, body.previous_revision)

    @router.post(PROJECT + "/authorizations/{authorization_id}/decisions", response_model=Authorization)
    def record_decision(identity: Caller, org_id: UUID, project_id: UUID, authorization_id: UUID,
                        body: DecisionInput) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.DECIDE_AUTHORIZATION) as (connection, _):
            return data.decide_authorization(connection, org_id, project_id, identity.user_id,
                                             authorization_id, body.revision, body.decision, body.reason)

    return router
