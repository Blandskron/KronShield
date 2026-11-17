from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network

import pytest

from application.policy import ScopeReason, evaluate_scope
from domain.authorization import Attribution, Authorization, AuthorizationStatus, RuleEffect, ScopeRule, ScopeTarget


START = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
END = START + timedelta(hours=1)
TARGET = ScopeTarget("service.example", "lab", Attribution.FIRST_PARTY)
ALLOW = ScopeRule("allow-service", RuleEffect.ALLOW, TARGET.host)


@pytest.fixture
def authorization():
    return Authorization(
        id="mandate",
        revision=3,
        organization_id="org",
        project_id="project",
        delegator_id="asset-owner",
        document_reference="evidence-123",
        document_sha256="d" * 64,
        status=AuthorizationStatus.APPROVED,
        valid_from=START,
        valid_until=END,
        environment="lab",
        techniques=frozenset({"http-baseline"}),
        rules=(ALLOW,),
        verified_by="reviewer",
    )


def check(authorization, target=TARGET, *, at=START, **context):
    request = {"organization_id": "org", "project_id": "project", "technique": "http-baseline"}
    return evaluate_scope(authorization, target, clock=lambda: at, **(request | context))


@pytest.mark.parametrize(
    ("at", "reason"),
    [
        (START - timedelta(microseconds=1), ScopeReason.NOT_YET_VALID),
        (START, ScopeReason.ALLOWED),
        (END - timedelta(microseconds=1), ScopeReason.ALLOWED),
        (END, ScopeReason.EXPIRED),
    ],
)
def test_window_is_inclusive_at_start_and_exclusive_at_end(authorization, at, reason):
    decision = check(authorization, at=at.astimezone(timezone(timedelta(hours=-3))))

    assert decision.reason is reason
    assert decision.allowed is (reason is ScopeReason.ALLOWED)
    assert decision.checked_at == at
    assert decision.checked_at.tzinfo is timezone.utc
    assert (decision.authorization_id, decision.authorization_revision) == ("mandate", 3)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (AuthorizationStatus.DRAFT, ScopeReason.NOT_APPROVED),
        (AuthorizationStatus.REVOKED, ScopeReason.REVOKED),
    ],
)
def test_unapproved_and_revoked_authorizations_deny(authorization, status, reason):
    assert check(replace(authorization, status=status)).reason is reason


def test_missing_authorization_denies():
    assert check(None).reason is ScopeReason.MISSING_AUTHORIZATION


@pytest.mark.parametrize("field", ["organization_id", "project_id"])
def test_authorization_cannot_cross_project_or_tenant(authorization, field):
    decision = check(authorization, **{field: "other"})
    assert decision.reason is ScopeReason.PROJECT_MISMATCH
    assert decision.authorization_id is None
    assert decision.authorization_revision is None


@pytest.mark.parametrize(
    ("target", "technique", "reason"),
    [
        (replace(TARGET, environment="prod"), "http-baseline", ScopeReason.ENVIRONMENT_MISMATCH),
        (TARGET, "other-technique", ScopeReason.TECHNIQUE_NOT_ALLOWED),
        (replace(TARGET, host="other.example"), "http-baseline", ScopeReason.NO_ALLOW_RULE),
        (replace(TARGET, attribution=Attribution.UNKNOWN), "http-baseline", ScopeReason.UNKNOWN_ATTRIBUTION),
    ],
)
def test_scope_requires_matching_environment_technique_target_and_attribution(
    authorization, target, technique, reason
):
    assert check(authorization, target, technique=technique).reason is reason


@pytest.mark.parametrize("effect_first", [True, False])
def test_exclusion_precedes_positive_rule(authorization, effect_first):
    deny = ScopeRule("exclusion", RuleEffect.DENY, TARGET.host)
    rules = (deny, ALLOW) if effect_first else (ALLOW, deny)
    decision = check(replace(authorization, rules=rules))

    assert decision.reason is ScopeReason.EXCLUDED
    assert decision.rule_id == deny.id


def test_empty_rules_deny(authorization):
    assert check(replace(authorization, rules=())).reason is ScopeReason.NO_ALLOW_RULE


def test_rules_can_restrict_techniques_per_destination(authorization):
    auth = replace(
        authorization,
        techniques={"http-baseline", "tcp-scan"},
        rules=(replace(ALLOW, techniques={"http-baseline"}),),
    )
    assert check(auth).allowed
    assert check(auth, technique="tcp-scan").reason is ScopeReason.NO_ALLOW_RULE


@pytest.mark.parametrize(
    ("attribution", "owner", "reason"),
    [
        (Attribution.THIRD_PARTY, "hosting-a", ScopeReason.ALLOWED),
        (Attribution.THIRD_PARTY, "hosting-b", ScopeReason.THIRD_PARTY_NOT_ALLOWED),
        (Attribution.SHARED, "hosting-a", ScopeReason.THIRD_PARTY_NOT_ALLOWED),
        (Attribution.SHARED, "hosting-b", ScopeReason.THIRD_PARTY_NOT_ALLOWED),
    ],
)
def test_third_party_requires_explicit_identity_and_category(authorization, attribution, owner, reason):
    third_party_allow = replace(
        ALLOW, id="allow-hosting-a", attribution=Attribution.THIRD_PARTY, third_party_id="hosting-a"
    )
    target = replace(TARGET, attribution=attribution, third_party_id=owner)

    assert check(authorization, target).reason is ScopeReason.THIRD_PARTY_NOT_ALLOWED
    decision = check(replace(authorization, rules=(ALLOW, third_party_allow)), target)
    assert decision.reason is reason
    assert decision.rule_id == (third_party_allow.id if decision.allowed else None)


def test_general_exclusion_also_applies_to_shared_target(authorization):
    target = replace(TARGET, attribution=Attribution.SHARED, third_party_id="shared-a")
    allow = replace(ALLOW, attribution=Attribution.SHARED, third_party_id="shared-a")
    deny = ScopeRule("exclude-shared-host", RuleEffect.DENY, TARGET.host)
    decision = check(replace(authorization, rules=(allow, deny)), target)

    assert decision.reason is ScopeReason.EXCLUDED
    assert decision.rule_id == deny.id


@pytest.mark.parametrize("host", ["team.example", "notteam.example", "a.team.example.other"])
def test_subdomain_rule_excludes_apex_and_unrelated_suffixes(authorization, host):
    rule = ScopeRule("subdomains", RuleEffect.ALLOW, "team.example", subdomains=True)
    auth = replace(authorization, rules=(rule,))

    assert check(auth, replace(TARGET, host=host)).reason is ScopeReason.NO_ALLOW_RULE
    assert check(auth, replace(TARGET, host="a.team.example")).rule_id == rule.id


@pytest.mark.parametrize(
    ("network", "member", "outside"),
    [("192.0.2.0/28", "192.0.2.2", "192.0.2.32"), ("2001:db8::/48", "2001:db8::4", "2001:db9::4")],
)
def test_cidr_is_matched_against_a_typed_address(authorization, network, member, outside):
    rule = ScopeRule("network", RuleEffect.ALLOW, ip_network(network), ports={443})
    auth = replace(authorization, rules=(rule,))

    assert check(auth, replace(TARGET, host=ip_address(member), port=443)).rule_id == rule.id
    assert not check(auth, replace(TARGET, host=ip_address(outside), port=443)).allowed
    assert not check(auth, replace(TARGET, host=ip_address(member), port=8443)).allowed


def test_application_scope_uses_scheme_port_method_and_path_segments(authorization):
    target = replace(TARGET, port=443, scheme="https", method="GET", path=("api", "status"))
    rule = replace(ALLOW, scheme="https", ports={443}, methods={"GET"}, path_prefix=("api",))
    auth = replace(authorization, rules=(rule,))

    assert check(auth, target).rule_id == rule.id
    for changes in ({"path": ("api-private",)}, {"method": "POST"}, {"scheme": "http"}, {"port": 8443}):
        assert check(auth, replace(target, **changes)).reason is ScopeReason.NO_ALLOW_RULE


def test_application_exclusion_cannot_be_overridden_by_broad_host_allow(authorization):
    deny = ScopeRule("exclude-admin", RuleEffect.DENY, TARGET.host, path_prefix=("admin",))
    target = replace(TARGET, port=443, scheme="https", method="GET", path=("admin", "status"))
    decision = check(replace(authorization, rules=(ALLOW, deny)), target)

    assert decision.reason is ScopeReason.EXCLUDED
    assert decision.rule_id == deny.id


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_from": START.replace(tzinfo=None)},
        {"valid_until": START},
        {"revision": 0},
        {"verified_by": None},
        {"document_sha256": "not-a-digest"},
        {"rules": (ALLOW, ALLOW)},
    ],
)
def test_invalid_authorization_is_rejected_at_construction(authorization, changes):
    with pytest.raises(ValueError):
        replace(authorization, **changes)


def test_authorization_and_rules_take_immutable_snapshots(authorization):
    techniques = {"http-baseline"}
    ports = {443}
    rules = [replace(ALLOW, ports=ports)]
    auth = replace(authorization, techniques=techniques, rules=rules)

    techniques.clear()
    ports.clear()
    rules.clear()
    assert auth.rules[0].ports == frozenset({443})
    assert auth.techniques == frozenset({"http-baseline"})
    with pytest.raises(FrozenInstanceError):
        auth.revision = 4


def test_naive_clock_cannot_grant_authorization(authorization):
    with pytest.raises(ValueError, match="timezone-aware"):
        check(authorization, at=START.replace(tzinfo=None))
