"""Public API response models and health probes."""

from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_REVISION = "0006_pilot_memberships"
API_VERSION = "1.0.0"


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldProblem(Output):
    field: list[str | int]
    type: str


class Problem(Output):
    type: str
    title: str
    status: int
    code: str
    detail: str
    request_id: UUID
    errors: list[FieldProblem] | None = None


class Health(Output):
    status: Literal["ok", "ready"]


class SessionInfo(Output):
    user_id: UUID
    source: Literal["web", "cli"]
    csrf_token: str | None = None
    org_id: UUID | None = None
    project_id: UUID | None = None
    organization_role: str | None = None
    project_role: str | None = None
    permissions: list[str] | None = None
    platform_admin: bool


T = TypeVar("T")


class Page(Output, Generic[T]):
    items: list[T]
    next_cursor: UUID | None


class Organization(Output):
    id: UUID
    slug: str
    state: Literal["active", "suspended"]
    version: int


class InventoryItem(Output):
    org_id: UUID
    id: UUID
    slug: str
    version: int


class Customer(InventoryItem):
    name: str


class Project(InventoryItem):
    customer_id: UUID
    environment: str
    state: Literal["active", "archived"]


class Target(InventoryItem):
    project_id: UUID
    environment: str
    canonical_address: str
    attribution: str
    third_party_id: str | None


class Assessment(Output):
    id: UUID
    actor_id: UUID
    label: str
    created_at: datetime


class Document(Output):
    id: UUID
    digest: str
    created_at: datetime


class ScopeRule(Output):
    effect: Literal["allow", "deny"]
    kind: Literal["fqdn", "subdomain", "ip", "cidr", "application"]
    destination: str
    scheme: str | None
    ports: list[int]
    path_prefix: list[str] | None


class Authorization(Output):
    id: UUID
    revision: int
    requester_id: UUID
    delegator_id: UUID
    document_evidence_id: UUID | None
    document_digest: str
    environment: str
    valid_from: datetime
    valid_until: datetime
    scope_rules: list[ScopeRule]
    limits: dict[str, int | float]
    created_at: datetime
    status: Literal["draft", "approved", "revoked"]
    effective_status: Literal["draft", "revoked", "scheduled", "active", "expired"]
    verifier_id: UUID | None
    approval_reason: str | None
    approved_at: datetime | None
    revoked_by: UUID | None
    revocation_reason: str | None
    revoked_at: datetime | None


class PlanAuthorization(Output):
    id: UUID
    revision: int
    latest_revision: int
    status: Literal["draft", "approved", "revoked"]
    document_digest: str
    document_evidence_id: UUID | None
    valid_from: datetime
    valid_until: datetime
    verifier_id: UUID | None
    scope_rules: list[ScopeRule]
    limits: dict[str, int | float]


class ReviewedTarget(Output):
    id: UUID
    version: int
    canonical_address: str
    environment: str
    attribution: str
    third_party_id: str | None
    reason: str
    rule_id: str | None


class Plan(Output):
    id: UUID
    actor_id: UUID
    hash: str
    checked_at: datetime
    schema_version: Literal[1]
    mode: Literal["dry-run"]
    profile_id: Literal["scope-review"]
    execution: Literal["disabled"]
    org_id: UUID
    project_id: UUID
    project_version: int
    assessment_id: UUID
    status: Literal["blocked", "reviewed"]
    denials: list[str]
    authorization: PlanAuthorization
    targets: list[ReviewedTarget]


class Verification(Output):
    id: UUID
    hash: str
    status: Literal["verified"]
    execution: Literal["disabled"]


class PlanEvent(Output):
    id: UUID
    kind: Literal["scope_review_recorded"]
    created_at: datetime


class PlanEvents(Output):
    items: list[PlanEvent]


class ImportSummary(Output):
    id: UUID
    source_format: Literal["json", "sqlite"]
    source_digest: str
    finding_count: int
    origin: Literal["legacy"]
    confidence: Literal["unverified"]


class ImportReceipt(ImportSummary):
    duplicate: bool


class LegacyFinding(Output):
    record_key: str
    target_url: str
    observed_url: str | None
    type: str
    detail: str
    reported_status: str | None
    reported_confidence: str | None
    origin: Literal["legacy"]
    confidence: Literal["unverified"]


class ImportDetail(ImportSummary):
    actor_id: UUID
    created_at: datetime
    findings: list[LegacyFinding] = Field(max_length=1000)
