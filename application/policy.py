"""Evaluate an authorization revision without DNS, network or persistence."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from domain.authorization import (
    Attribution,
    Authorization,
    AuthorizationStatus,
    RuleEffect,
    ScopeTarget,
    utc_instant,
)


class ScopeReason(str, Enum):
    ALLOWED = "allowed"
    MISSING_AUTHORIZATION = "missing_authorization"
    PROJECT_MISMATCH = "project_mismatch"
    NOT_APPROVED = "not_approved"
    REVOKED = "revoked"
    NOT_YET_VALID = "not_yet_valid"
    EXPIRED = "expired"
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    EXCLUDED = "excluded"
    TECHNIQUE_NOT_ALLOWED = "technique_not_allowed"
    UNKNOWN_ATTRIBUTION = "unknown_attribution"
    THIRD_PARTY_NOT_ALLOWED = "third_party_not_allowed"
    NO_ALLOW_RULE = "no_allow_rule"


@dataclass(frozen=True)
class ScopeDecision:
    reason: ScopeReason
    checked_at: datetime
    authorization_id: str | None = None
    authorization_revision: int | None = None
    rule_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.reason is ScopeReason.ALLOWED


def evaluate_scope(
    authorization: Authorization | None,
    target: ScopeTarget,
    *,
    organization_id: str,
    project_id: str,
    technique: str,
    clock: Callable[[], datetime],
) -> ScopeDecision:
    """Check the supplied revision against a trusted project and inventory context."""
    now = utc_instant(clock())
    if authorization is None:
        return ScopeDecision(ScopeReason.MISSING_AUTHORIZATION, now)
    if (authorization.organization_id, authorization.project_id) != (organization_id, project_id):
        return ScopeDecision(ScopeReason.PROJECT_MISMATCH, now)

    def decision(reason: ScopeReason, rule_id: str | None = None) -> ScopeDecision:
        return ScopeDecision(reason, now, authorization.id, authorization.revision, rule_id)

    if authorization.status is AuthorizationStatus.REVOKED:
        return decision(ScopeReason.REVOKED)
    if authorization.status is not AuthorizationStatus.APPROVED:
        return decision(ScopeReason.NOT_APPROVED)
    if now < authorization.valid_from:
        return decision(ScopeReason.NOT_YET_VALID)
    if now >= authorization.valid_until:
        return decision(ScopeReason.EXPIRED)
    if target.environment != authorization.environment:
        return decision(ScopeReason.ENVIRONMENT_MISMATCH)

    matching_allows = []
    for rule in authorization.rules:
        if (rule.techniques and technique not in rule.techniques) or not rule.matches(target):
            continue
        if rule.effect is RuleEffect.DENY:
            if rule.matches_attribution(target):
                return decision(ScopeReason.EXCLUDED, rule.id)
        else:
            matching_allows.append(rule)

    if technique not in authorization.techniques:
        return decision(ScopeReason.TECHNIQUE_NOT_ALLOWED)
    if target.attribution is Attribution.UNKNOWN:
        return decision(ScopeReason.UNKNOWN_ATTRIBUTION)
    for rule in matching_allows:
        if rule.matches_attribution(target):
            return decision(ScopeReason.ALLOWED, rule.id)
    if matching_allows and target.third_party_id is not None:
        return decision(ScopeReason.THIRD_PARTY_NOT_ALLOWED)
    return decision(ScopeReason.NO_ALLOW_RULE)
