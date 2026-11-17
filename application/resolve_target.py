"""Resolve one authorized operation into numeric connection candidates."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Protocol

from application.policy import ScopeReason, evaluate_scope
from domain.authorization import Address, Attribution, Authorization, ScopeTarget, canonical_address
from domain.targets import AddressPolicy, canonical_host


class ResolutionFailure(Exception):
    """The configured resolver could not provide a complete, consistent answer."""


@dataclass(frozen=True)
class DnsRecords:
    aliases: tuple[str, ...]
    addresses: tuple[Address, ...]


class TargetResolver(Protocol):
    def resolve(self, host: str) -> DnsRecords: ...


class DestinationReason(str, Enum):
    SCOPE_DENIED = "scope_denied"
    DNS_FAILED = "dns_failed"
    INVALID_DNS_ANSWER = "invalid_dns_answer"
    ADDRESS_BLOCKED = "address_blocked"
    MISSING_ATTRIBUTION = "missing_attribution"


class DestinationDenied(Exception):
    def __init__(self, reason: DestinationReason, scope_reason: ScopeReason | None = None):
        super().__init__(reason.value)
        self.reason = reason
        self.scope_reason = scope_reason


@dataclass(frozen=True)
class ResolvedTarget:
    target: ScopeTarget
    aliases: tuple[str, ...]
    addresses: tuple[Address, ...]


def resolve_target(
    target: ScopeTarget,
    authorization: Authorization | None,
    *,
    organization_id: str,
    project_id: str,
    technique: str,
    clock: Callable[[], datetime],
    resolver: TargetResolver,
    address_policy: AddressPolicy,
    lookup_attribution: Callable[[str | Address], tuple[Attribution, str | None] | None],
) -> ResolvedTarget:
    """Require coverage of the original host, each alias and every effective IP."""
    def require_scope(candidate: ScopeTarget) -> None:
        decision = evaluate_scope(
            authorization, candidate, organization_id=organization_id, project_id=project_id,
            technique=technique, clock=clock,
        )
        if not decision.allowed:
            raise DestinationDenied(DestinationReason.SCOPE_DENIED, decision.reason)

    def require_attributed_scope(host: str | Address) -> None:
        attribution = lookup_attribution(host)
        if attribution is None:
            raise DestinationDenied(DestinationReason.MISSING_ATTRIBUTION)
        kind, third_party_id = attribution
        require_scope(replace(target, host=host, attribution=kind, third_party_id=third_party_id))

    def require_address(address: Address) -> None:
        if not address_policy.permits(address):
            raise DestinationDenied(DestinationReason.ADDRESS_BLOCKED)

    if not isinstance(target.host, str):
        require_scope(target)
        require_address(target.host)
        return ResolvedTarget(target, (), (target.host,))

    require_scope(target)
    try:
        records = resolver.resolve(target.host)
    except ResolutionFailure:
        raise DestinationDenied(DestinationReason.DNS_FAILED) from None
    if len(records.aliases) > 8 or not 1 <= len(records.addresses) <= 64:
        raise DestinationDenied(DestinationReason.INVALID_DNS_ANSWER)

    aliases = []
    seen = {target.host}
    try:
        for name in records.aliases:
            alias = canonical_host(name)
            if not isinstance(alias, str) or alias in seen:
                raise ValueError("Invalid CNAME chain")
            seen.add(alias)
            aliases.append(alias)
        addresses = tuple(dict.fromkeys(canonical_address(address) for address in records.addresses))
    except ValueError:
        raise DestinationDenied(DestinationReason.INVALID_DNS_ANSWER) from None

    for alias in aliases:
        require_attributed_scope(alias)
    for address in addresses:
        require_address(address)
        require_attributed_scope(address)
    return ResolvedTarget(target, tuple(aliases), addresses)
