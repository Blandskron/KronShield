"""Project permissions derived from stored memberships."""

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class AccessError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


class Action(str, Enum):
    READ = "project:read"
    MANAGE_ASSESSMENTS = "assessments:manage"
    MANAGE_TARGETS = "targets:manage"
    REQUEST_AUTHORIZATION = "authorizations:request"
    DECIDE_AUTHORIZATION = "authorizations:decide"
    MANAGE_PROJECT = "project:manage"


PROJECT_PERMISSIONS = {
    "viewer": frozenset({Action.READ}),
    "operator": frozenset({Action.READ, Action.MANAGE_TARGETS, Action.REQUEST_AUTHORIZATION, Action.MANAGE_ASSESSMENTS}),
    "approver": frozenset({Action.READ, Action.DECIDE_AUTHORIZATION}),
    "project_admin": frozenset({Action.READ, Action.MANAGE_PROJECT}),
}


@dataclass(frozen=True)
class ProjectAccess:
    org_id: UUID
    project_id: UUID
    user_id: UUID
    organization_role: str
    project_role: str
    permissions: frozenset[Action]


def authorize_project(
    org_id: UUID,
    project_id: UUID,
    user_id: UUID,
    membership: tuple[str, str] | None,
    action: Action,
) -> ProjectAccess:
    if membership is None:
        raise AccessError(404, "project_not_found")
    organization_role, project_role = membership
    permissions = PROJECT_PERMISSIONS.get(project_role, frozenset())
    if action not in permissions:
        raise AccessError(403, "permission_denied")
    return ProjectAccess(org_id, project_id, user_id, organization_role, project_role, permissions)
