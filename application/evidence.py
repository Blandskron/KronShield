"""Policy and minimal projections for authorized offline evidence."""

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from application.access import AccessError, Action, ProjectAccess
from domain.team_modes import TEAM_CATALOG, CapabilityStep, TeamId, TeamStep, ToolId


MAX_SOURCE_BYTES = 1024 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[int, Field(strict=True, ge=1, le=2147483647)]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class SourceKind(str, Enum):
    CONTROL_OBSERVATIONS = "control-observations-v1"
    EVENT_BATCH = "event-batch-v1"
    LEGACY = "legacy-reference-v1"


class Classification(str, Enum):
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class Source(EvidenceModel):
    digest: Digest
    kind: SourceKind
    size_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_SOURCE_BYTES)] | None = None
    target_id: UUID
    classification: Classification
    capability: ToolId
    legacy_id: UUID | None = None
    retain_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_reference(self):
        if self.kind is SourceKind.LEGACY:
            if self.legacy_id is None or self.size_bytes is not None:
                raise ValueError("Legacy evidence requires an existing import reference")
        elif self.size_bytes is None or self.legacy_id is not None:
            raise ValueError("Uploaded evidence requires its exact byte count")
        if self.kind is SourceKind.EVENT_BATCH and self.capability is not ToolId.EVENT_REVIEW:
            raise ValueError("Event batches require the event review capability")
        return self


class PermissionSpec(EvidenceModel):
    plan_id: UUID
    plan_hash: Digest
    mode_id: TeamId
    mode_version: Revision
    mode_digest: Digest
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    purpose: Literal["offline-review"] = "offline-review"
    allow_local_inference: bool = False
    sources: Annotated[tuple[Source, ...], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def check_limits(self):
        if self.valid_from >= self.valid_until:
            raise ValueError("Expected a positive validity window")
        if len({source.digest for source in self.sources}) != len(self.sources):
            raise ValueError("Expected unique source digests")
        if self.allow_local_inference and any(source.classification is Classification.RESTRICTED for source in self.sources):
            raise ValueError("Restricted evidence cannot be shared with inference")
        if any(source.retain_until is not None and not self.valid_from < source.retain_until <= self.valid_until
               for source in self.sources):
            raise ValueError("Retention must end within the permission window")
        return self


def check_plan(spec: PermissionSpec, plan: dict, caller: ProjectAccess) -> None:
    if (str(caller.org_id), str(caller.project_id)) != (str(plan["org_id"]), str(plan["project_id"])):
        raise AccessError(404, "plan_not_found")
    if (str(spec.plan_id), spec.plan_hash) != (str(plan["id"]), plan["hash"]) or plan["status"] != "reviewed":
        raise AccessError(409, "evidence_plan_mismatch")
    scope = plan["authorization"]
    if (spec.valid_from < datetime.fromisoformat(scope["valid_from"])
            or spec.valid_until > datetime.fromisoformat(scope["valid_until"])):
        raise AccessError(422, "evidence_window_outside_mandate")
    targets = {str(target["id"]) for target in plan["targets"]
               if target["reason"] == "allowed" and target["attribution"] == "first_party"}
    if any(str(source.target_id) not in targets for source in spec.sources):
        raise AccessError(422, "evidence_asset_not_allowed")
    mode = TEAM_CATALOG[spec.mode_id]
    if (spec.mode_version, spec.mode_digest) != (mode.version, mode.digest):
        raise AccessError(409, "evidence_mode_changed")
    stages = (TEAM_CATALOG[step.team] for step in mode.workflow if isinstance(step, TeamStep))
    tools = {step.tool for stage in (mode, *stages) for step in stage.workflow if isinstance(step, CapabilityStep)}
    if any(source.capability not in tools for source in spec.sources):
        raise AccessError(422, "evidence_capability_not_allowed")


def check_decider(caller: ProjectAccess, requester: UUID) -> None:
    if Action.DECIDE_EVIDENCE not in caller.permissions:
        raise AccessError(403, "permission_denied")
    if caller.user_id == requester:
        raise AccessError(403, "approval_requires_distinct_actor")


def retention_deadline(spec: PermissionSpec, source: Source) -> datetime:
    days = 7 if source.classification is Classification.RESTRICTED else 30
    return min(spec.valid_until, source.retain_until or spec.valid_until, spec.valid_from + timedelta(days=days))


def authorize_use(spec: PermissionSpec, plan: dict, caller: ProjectAccess, *, requester: UUID,
                  approver: UUID | None, status: str, now: datetime,
                  purpose: Literal["offline-review", "local-inference"], digest: str) -> Source:
    is_requester = caller.user_id == requester and Action.REQUEST_EVIDENCE in caller.permissions
    is_approver = caller.user_id == approver and Action.DECIDE_EVIDENCE in caller.permissions
    if not (is_requester or is_approver):
        raise AccessError(404, "evidence_not_found")
    check_plan(spec, plan, caller)
    if status != "approved" or not spec.valid_from <= now < spec.valid_until:
        raise AccessError(409, "evidence_permission_inactive")
    source = next((item for item in spec.sources if item.digest == digest), None)
    if source is None:
        raise AccessError(404, "evidence_not_found")
    if now >= retention_deadline(spec, source):
        raise AccessError(409, "evidence_retention_elapsed")
    if purpose != spec.purpose and (
        purpose != "local-inference" or not spec.allow_local_inference or source.classification is not Classification.INTERNAL
    ):
        raise AccessError(403, "evidence_purpose_denied")
    return source


class ControlObservation(EvidenceModel):
    control: Literal["access-review", "logging", "backup", "configuration"]
    result: Literal["observed", "missing", "inconclusive"]


class ControlObservations(EvidenceModel):
    target_id: UUID
    observations: Annotated[tuple[ControlObservation, ...], Field(min_length=1, max_length=100)]


def _utc(timestamp: datetime) -> datetime:
    try:
        return timestamp.astimezone(timezone.utc)
    except OverflowError:
        raise ValueError("Timestamp is outside the supported UTC range") from None


class TriageEvent(EvidenceModel):
    event_id: UUID
    occurred_at: AwareDatetime = Field(strict=True)
    kind: Literal["login-success", "login-failure", "privilege-change", "configuration-change"]

    @field_validator("occurred_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)


class EventBatch(EvidenceModel):
    target_id: UUID
    producer: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
    window_start: AwareDatetime = Field(strict=True)
    window_end: AwareDatetime = Field(strict=True)
    events: Annotated[tuple[TriageEvent, ...], Field(max_length=2000)]

    @field_validator("window_start", "window_end")
    @classmethod
    def normalize_window(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def check_window(self):
        if not self.window_start < self.window_end:
            raise ValueError("Expected a positive event window")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("Expected unique event IDs")
        if any(not self.window_start <= event.occurred_at < self.window_end for event in self.events):
            raise ValueError("Event is outside the batch window")
        return self


UPLOAD_MODELS = {
    SourceKind.CONTROL_OBSERVATIONS: ControlObservations,
    SourceKind.EVENT_BATCH: EventBatch,
}


def project_upload(source: Source, payload: bytes) -> dict:
    model = UPLOAD_MODELS.get(source.kind)
    if model is None:
        raise AccessError(422, "evidence_kind_mismatch")
    if len(payload) != source.size_bytes or sha256(payload).hexdigest() != source.digest:
        raise AccessError(422, "evidence_source_mismatch")
    try:
        content = model.model_validate_json(payload)
    except ValidationError:
        raise AccessError(422, "invalid_evidence_source") from None
    if content.target_id != source.target_id:
        raise AccessError(422, "evidence_asset_not_allowed")
    if isinstance(content, EventBatch):
        ordered = tuple(sorted(content.events, key=lambda event: (event.occurred_at, event.event_id)))
        content = content.model_copy(update={"events": ordered})
    return content.model_dump(mode="json")


def project_plan(plan: dict, source: Source) -> dict:
    target = next(target for target in plan["targets"] if str(target["id"]) == str(source.target_id))
    return {
        "plan_id": str(plan["id"]), "plan_hash": plan["hash"], "status": plan["status"],
        "authorization_revision": plan["authorization"]["revision"],
        "target_id": str(source.target_id), "target_version": target["version"],
        "attribution": target["attribution"], "outcome": target["reason"],
    }


def project_legacy(source: Source, record: dict) -> dict:
    if (str(source.legacy_id), source.digest) != (str(record["id"]), record["source_digest"]):
        raise AccessError(404, "evidence_not_found")
    return {"id": str(source.legacy_id), "target_id": str(source.target_id), "origin": "legacy",
            "confidence": "unverified", "finding_count": record["finding_count"]}


def projection_bytes(value: dict | list[dict]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
