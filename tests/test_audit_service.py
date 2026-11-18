from datetime import datetime, timedelta, timezone

import pytest

from application.audit_service import ActiveAuditDisabled, Profile, audit_website, prepare_plan
from application.policy import ScopeReason
from core import recon, scanner, sqli, xss
from domain.authorization import Attribution, Authorization, AuthorizationStatus, RuleEffect, ScopeRule
from domain.budget import BudgetLimits
from domain.targets import canonical_http_target
from gpt import client, prompts


def test_legacy_application_entry_point_denies_even_when_given_a_token():
    with pytest.raises(ActiveAuditDisabled, match="audit plan"):
        audit_website("https://scope.example", "fixture-token")


def test_legacy_direct_network_and_payload_entry_points_were_removed():
    for module, name in (
        (recon, "run"), (scanner, "scan_ports"), (xss, "test"), (sqli, "test"),
        (client, "generate_payloads"), (prompts, "xss_prompt"), (prompts, "sqli_prompt"),
    ):
        assert not hasattr(module, name)


def test_plan_uses_injected_authorization_and_applies_profile_technique():
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    target = canonical_http_target("https://scope.example:8443", environment="lab", attribution=Attribution.FIRST_PARTY)
    authorization = Authorization(
        "auth", 1, "org", "project", "owner", "proof", "a" * 64, AuthorizationStatus.APPROVED,
        now - timedelta(minutes=1), now + timedelta(minutes=1), "lab", frozenset({"http-baseline"}),
        (ScopeRule("target", RuleEffect.ALLOW, target.host),), "reviewer",
    )
    limits = BudgetLimits(max_operations=4)
    context = {"authorization": authorization, "organization_id": "org", "project_id": "project", "clock": lambda: now}

    web = prepare_plan(target, Profile.WEB_BASELINE, limits, **context)
    tcp = prepare_plan(target, Profile.TCP_BASELINE, limits, **context)

    assert web.scope.allowed
    assert web.scope.rule_id == "target"
    assert web.target == target
    assert web.limits.max_operations == 4
    assert tcp.scope.reason is ScopeReason.TECHNIQUE_NOT_ALLOWED
    assert tcp.target.scheme is None and tcp.target.port == 8443
    with pytest.raises(ActiveAuditDisabled):
        audit_website("https://scope.example:8443")
