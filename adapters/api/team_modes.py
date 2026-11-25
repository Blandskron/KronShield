"""Expose the project team catalog and its shared selection."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from adapters.api.auth import RequestAuth, RequestIdentity
from adapters.api.contract import Output
from adapters.api.engagement_models import Contract
from adapters.api.engagements import IfMatch, _version
from application.access import Action
from domain.team_modes import TEAM_CATALOG, TeamId, TeamMode
from infra.auth_store import PostgresAuthStore
from infra.team_selections import get_selection, set_selection


class TeamModeEntry(Output):
    manifest: TeamMode
    digest: str
    eligible_for_analysis: bool


class TeamModes(Output):
    items: list[TeamModeEntry]


class SelectionInput(Contract):
    mode_id: TeamId


class SelectionRevision(Output):
    version: int
    mode_id: TeamId
    mode_version: int
    mode_digest: str
    actor_id: UUID
    created_at: datetime


class TeamSelection(Output):
    version: int = Field(ge=0)
    selection: SelectionRevision | None


def _selection_response(response: Response, selection: dict | None) -> dict:
    version = selection["version"] if selection else 0
    response.headers["ETag"] = f'"{version}"'
    return {"version": version, "selection": selection}


def team_mode_routes(auth: RequestAuth, store: PostgresAuthStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects/{project_id}")
    Caller = Annotated[RequestIdentity, Depends(auth.identity)]

    @router.get("/team-modes", response_model=TeamModes)
    def list_modes(identity: Caller, org_id: UUID, project_id: UUID) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ):
            return {"items": [
                {"manifest": mode, "digest": mode.digest, "eligible_for_analysis": mode.eligible_for_analysis}
                for mode in TEAM_CATALOG.values()
            ]}

    @router.get("/team-selection", response_model=TeamSelection)
    def read_selection(identity: Caller, org_id: UUID, project_id: UUID, response: Response) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.READ) as (connection, caller):
            return _selection_response(response, get_selection(connection, caller))

    @router.put("/team-selection", response_model=TeamSelection)
    def write_selection(identity: Caller, org_id: UUID, project_id: UUID, body: SelectionInput,
                        response: Response, if_match: IfMatch = None) -> dict:
        with store.project(identity.user_id, org_id, project_id, Action.MANAGE_PROJECT) as (connection, caller):
            expected_version = _version(if_match, allow_initial=True)
            selection = set_selection(connection, caller, TEAM_CATALOG[body.mode_id], expected_version)
            return _selection_response(response, selection)

    return router
