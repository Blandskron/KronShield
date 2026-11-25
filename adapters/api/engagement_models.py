"""Request contracts for inventory and authorization records."""

from ipaddress import ip_address, ip_network
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from domain.authorization import Attribution, RuleEffect, ScopeRule, ScopeTarget
from domain.budget import BudgetLimits
from domain.targets import canonical_host, canonical_http_target


Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Environment = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Address = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
Revision = Annotated[int, Field(strict=True, ge=1, le=2147483647)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class OrganizationInput(Contract):
    slug: Slug
    admin_id: UUID


class OrganizationStopInput(Contract):
    enabled: StrictBool
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class CustomerInput(Contract):
    slug: Slug
    name: Name


class ProjectInput(Contract):
    slug: Slug
    customer_id: UUID
    environment: Environment


class TargetInput(Contract):
    slug: Slug
    environment: Environment
    address: Address
    attribution: Attribution
    third_party_id: Name | None = None

    def storage_values(self) -> dict:
        values = self.model_dump(mode="json", exclude={"address"})
        if "://" in self.address:
            target = canonical_http_target(self.address, environment=self.environment,
                                           attribution=self.attribution, third_party_id=self.third_party_id)
            host = str(target.host)
            authority = f"[{host}]" if ":" in host else host
            if (target.scheme, target.port) not in {("http", 80), ("https", 443)}:
                authority += f":{target.port}"
            path = "/" + "/".join(target.path or ())
            if target.path and target.trailing_slash:
                path += "/"
            canonical = f"{target.scheme}://{authority}{path}"
        else:
            target = ScopeTarget(canonical_host(self.address), self.environment, self.attribution, self.third_party_id)
            canonical = str(target.host)
        values["canonical_address"] = canonical
        return values


class Patch(Contract):
    @model_validator(mode="after")
    def require_changes(self):
        values = self.model_dump(exclude_unset=True)
        if not values or any(value is None for key, value in values.items() if key != "third_party_id"):
            raise ValueError("Expected at least one non-null change")
        return self


class OrganizationPatch(Patch):
    slug: Slug | None = None
    state: Literal["active", "suspended"] | None = None


class CustomerPatch(Patch):
    slug: Slug | None = None
    name: Name | None = None


class ProjectPatch(Patch):
    slug: Slug | None = None
    state: Literal["active", "archived"] | None = None


class TargetPatch(Patch):
    slug: Slug | None = None
    environment: Environment | None = None
    address: Address | None = None
    attribution: Attribution | None = None
    third_party_id: Name | None = None


class ScopeInput(Contract):
    effect: RuleEffect
    kind: Literal["fqdn", "subdomain", "ip", "cidr", "application"]
    destination: Address

    def snapshot(self) -> dict:
        destination, scheme, port, path = self.destination, None, None, None
        if self.kind == "application":
            target = canonical_http_target(destination, environment="validation", attribution=Attribution.FIRST_PARTY)
            destination, scheme, port, path = target.host, target.scheme, target.port, target.path
        elif self.kind == "cidr":
            destination = ip_network(destination, strict=True)
        elif self.kind == "ip":
            destination = ip_address(destination)
        else:
            destination = canonical_host(destination)
            if not isinstance(destination, str):
                raise ValueError("DNS scope rule requires a DNS name")
        rule = ScopeRule(
            id="validate", effect=self.effect, destination=destination, subdomains=self.kind == "subdomain",
            scheme=scheme, ports=frozenset({port}) if port is not None else frozenset(), path_prefix=path,
        )
        return {
            "effect": rule.effect.value, "kind": self.kind, "destination": str(rule.destination),
            "scheme": rule.scheme, "ports": sorted(rule.ports), "path_prefix": rule.path_prefix,
        }


class AuthorizationInput(Contract):
    document_evidence_id: UUID
    delegator_id: UUID
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    scope_rules: Annotated[list[ScopeInput], Field(min_length=1, max_length=50)]
    limits: BudgetLimits

    @model_validator(mode="after")
    def check_window(self):
        if self.valid_from >= self.valid_until:
            raise ValueError("Expected a positive validity window")
        return self


class AuthorizationRevision(AuthorizationInput):
    previous_revision: Revision


class DecisionInput(Contract):
    revision: Revision
    decision: Literal["approve", "revoke"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
