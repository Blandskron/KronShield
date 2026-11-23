"""Manage membership without expanding normal tenant visibility."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text

from adapters.api.auth import RequestAuth, RequestIdentity
from adapters.api.contract import Output
from adapters.api.engagement_models import Contract
from application.access import AccessError
from infra.auth_store import PostgresAuthStore
from infra.engagements import inventory_item, organization_role
from infra.tenancy import tenant_transaction


OrgRole = Literal["member", "org_admin"]
ProjectRole = Literal["viewer", "operator", "approver", "project_admin"]


class MembershipInput(Contract):
    user_id: UUID
    role_id: OrgRole | ProjectRole


class Membership(Output):
    user_id: UUID
    role_id: str


class MembershipPage(Output):
    items: list[Membership]
    next_cursor: UUID | None


def membership_routes(auth: RequestAuth, store: PostgresAuthStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/memberships")
    Caller = Annotated[RequestIdentity, Depends(auth.identity)]

    def operate(identity, org, project, *, after=None, limit=50, change=None, remove=None):
        with tenant_transaction(store.engine, user_id=identity.user_id, org_id=org, project_id=project) as connection:
            inventory_item(connection, "organization", org)
            if organization_role(connection, identity.user_id, org) != "org_admin":
                raise AccessError(403, "permission_denied")
            connection.execute(text("SELECT set_config('pentest_agent.manage_memberships', 'on', true)"))
            if project:
                inventory_item(connection, "project", project)
            table = "project_membership" if project else "organization_membership"
            scope = "org_id = :org AND project_id = :project" if project else "org_id = :org"
            args = {"org": org, "project": project}
            if change or remove:
                user = change.user_id if change else remove
                if user == identity.user_id:
                    raise AccessError(403, "self_membership_change_denied")
                args["user"] = user
                if remove:
                    deleted = connection.execute(text(f"""
                        DELETE FROM pentest_agent.{table} WHERE {scope} AND user_id = :user
                    """), args).rowcount
                    if not deleted:
                        raise AccessError(404, "membership_not_found")
                    return None
                choices = {"viewer", "operator", "approver", "project_admin"} if project else {"member", "org_admin"}
                if change.role_id not in choices:
                    raise AccessError(422, "invalid_membership_role")
                fields = "org_id, project_id, user_id" if project else "org_id, user_id"
                values = ":org, :project, :user" if project else ":org, :user"
                connection.execute(text(f"""
                    INSERT INTO pentest_agent.{table} ({fields}, role_id) VALUES ({values}, :role)
                    ON CONFLICT ({fields}) DO UPDATE SET role_id = EXCLUDED.role_id
                """), {**args, "role": change.role_id})
                return {"user_id": user, "role_id": change.role_id}

            rows = connection.execute(text(f"""
                SELECT user_id, role_id FROM pentest_agent.{table} WHERE {scope}
                AND (CAST(:after AS uuid) IS NULL OR user_id > :after) ORDER BY user_id LIMIT :limit
            """), {**args, "after": after, "limit": limit + 1}).mappings().all()
            page = rows[:limit]
            return {"items": [dict(row) for row in page],
                    "next_cursor": page[-1]["user_id"] if len(rows) > limit else None}

    @router.get("", response_model=MembershipPage)
    def members(identity: Caller, org_id: UUID, project_id: UUID | None = None, after: UUID | None = None,
                limit: Annotated[int, Query(ge=1, le=100)] = 50) -> dict:
        return operate(identity, org_id, project_id, after=after, limit=limit)

    @router.put("", response_model=Membership)
    def save(identity: Caller, org_id: UUID, body: MembershipInput, project_id: UUID | None = None) -> dict:
        return operate(identity, org_id, project_id, change=body)

    @router.delete("/{user_id}", status_code=204, response_class=Response)
    def delete(identity: Caller, org_id: UUID, user_id: UUID, project_id: UUID | None = None) -> Response:
        operate(identity, org_id, project_id, remove=user_id)
        return Response(status_code=204)

    return router
