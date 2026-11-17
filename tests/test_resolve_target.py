from dataclasses import replace
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network
from unittest.mock import Mock

import pytest

from application.policy import ScopeReason
from application.resolve_target import DestinationDenied, DestinationReason, DnsRecords, ResolutionFailure, resolve_target
from domain.authorization import Attribution, Authorization, AuthorizationStatus, RuleEffect, ScopeRule
from domain.targets import AddressPolicy, canonical_http_target


NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
BASE = canonical_http_target("https://scope.example", environment="lab", attribution=Attribution.FIRST_PARTY)
IP = ip_address("8.8.8.8")
RULES = (
    ScopeRule("nominal", RuleEffect.ALLOW, BASE.host),
    ScopeRule("alias", RuleEffect.ALLOW, "alias.example"),
    ScopeRule("ip4", RuleEffect.ALLOW, ip_network("8.8.8.0/24")),
    ScopeRule("ip6", RuleEffect.ALLOW, ip_network("2606:4700::/32")),
)


@pytest.fixture
def authorization():
    return Authorization(
        "auth", 1, "org", "project", "owner", "evidence", "a" * 64, AuthorizationStatus.APPROVED,
        NOW - timedelta(minutes=1), NOW + timedelta(minutes=1), "lab",
        frozenset({"web"}), RULES, "reviewer",
    )


def resolve(auth, resolver, target=BASE, **overrides):
    context = {
        "organization_id": "org", "project_id": "project", "technique": "web", "clock": lambda: NOW,
        "address_policy": AddressPolicy(), "lookup_attribution": lambda host: (Attribution.FIRST_PARTY, None),
    }
    return resolve_target(target, auth, resolver=resolver, **(context | overrides))


def test_resolution_checks_both_families_and_preserves_nominal_authority(authorization):
    ipv6 = ip_address("2606:4700::1111")
    resolver = Mock()
    resolver.resolve.return_value = DnsRecords(("ALIAS.example.",), (IP, ipv6, ip_address("::ffff:8.8.8.8")))
    attribution = Mock(return_value=(Attribution.FIRST_PARTY, None))

    result = resolve(authorization, resolver, lookup_attribution=attribution)

    resolver.resolve.assert_called_once_with(BASE.host)
    assert result.target == BASE
    assert result.aliases == ("alias.example",)
    assert result.addresses == (IP, ipv6)
    assert [call.args[0] for call in attribution.call_args_list] == ["alias.example", IP, ipv6]


def test_unapproved_nominal_host_does_not_query_dns(authorization):
    resolver = Mock()
    with pytest.raises(DestinationDenied) as err:
        resolve(replace(authorization, rules=RULES[1:]), resolver)
    assert err.value.scope_reason is ScopeReason.NO_ALLOW_RULE
    resolver.resolve.assert_not_called()


@pytest.mark.parametrize(
    ("aliases", "ips", "reason", "scope_reason"),
    [
        (("elsewhere.example",), (IP,), DestinationReason.SCOPE_DENIED, ScopeReason.NO_ALLOW_RULE),
        (("scope.example.",), (IP,), DestinationReason.INVALID_DNS_ANSWER, None),
        (("8.8.8.8",), (IP,), DestinationReason.INVALID_DNS_ANSWER, None),
        ((), (), DestinationReason.INVALID_DNS_ANSWER, None),
        ((), (IP, ip_address("::ffff:169.254.169.254")), DestinationReason.ADDRESS_BLOCKED, None),
        ((), (IP, ip_address("1.1.1.1")), DestinationReason.SCOPE_DENIED, ScopeReason.NO_ALLOW_RULE),
    ],
)
def test_one_forbidden_or_invalid_dns_record_denies_entire_answer(authorization, aliases, ips, reason, scope_reason):
    resolver = Mock()
    resolver.resolve.return_value = DnsRecords(aliases, ips)

    with pytest.raises(DestinationDenied) as err:
        resolve(authorization, resolver)
    assert err.value.reason is reason
    assert err.value.scope_reason is scope_reason


def test_alias_attribution_must_be_present_and_authorized(authorization):
    resolver = Mock()
    resolver.resolve.return_value = DnsRecords(("alias.example",), (IP,))
    with pytest.raises(DestinationDenied) as err:
        resolve(authorization, resolver, lookup_attribution=lambda host: None)
    assert err.value.reason is DestinationReason.MISSING_ATTRIBUTION

    with pytest.raises(DestinationDenied) as err:
        resolve(authorization, resolver, lookup_attribution=lambda host: (Attribution.SHARED, "provider"))
    assert err.value.scope_reason is ScopeReason.THIRD_PARTY_NOT_ALLOWED


def test_private_ip_also_requires_positive_scope_and_honors_exclusion(authorization):
    subnet = ip_network("10.20.30.0/24")
    ip = ip_address("10.20.30.2")
    resolver = Mock()
    resolver.resolve.return_value = DnsRecords((), (ip,))
    policy = AddressPolicy(private_networks=(subnet,))
    with pytest.raises(DestinationDenied) as err:
        resolve(authorization, resolver, address_policy=policy)
    assert err.value.scope_reason is ScopeReason.NO_ALLOW_RULE

    allow = ScopeRule("lab-ip", RuleEffect.ALLOW, subnet)
    allowed = replace(authorization, rules=(*RULES, allow))
    assert resolve(allowed, resolver, address_policy=policy).addresses == (ip,)
    deny = ScopeRule("excluded", RuleEffect.DENY, ip)
    with pytest.raises(DestinationDenied) as err:
        resolve(replace(allowed, rules=(*allowed.rules, deny)), resolver, address_policy=policy)
    assert err.value.scope_reason is ScopeReason.EXCLUDED


def test_scope_is_rechecked_after_dns_returns(authorization):
    resolver = Mock()
    resolver.resolve.return_value = DnsRecords((), (IP,))
    clock = Mock(side_effect=[NOW, authorization.valid_until])

    with pytest.raises(DestinationDenied) as err:
        resolve(authorization, resolver, clock=clock)
    assert err.value.scope_reason is ScopeReason.EXPIRED


def test_numeric_target_skips_dns_but_still_requires_scope_and_address_policy(authorization):
    resolver = Mock()
    direct = replace(BASE, host=IP)
    assert resolve(authorization, resolver, direct).addresses == (IP,)

    loopback = ip_address("127.0.0.1")
    rule = ScopeRule("loopback", RuleEffect.ALLOW, loopback)
    with pytest.raises(DestinationDenied) as err:
        resolve(replace(authorization, rules=(*RULES, rule)), resolver, replace(direct, host=loopback))
    assert err.value.reason is DestinationReason.ADDRESS_BLOCKED
    resolver.resolve.assert_not_called()


def test_ipv4_mapped_exclusion_covers_the_canonical_ipv4_destination(authorization):
    deny = ScopeRule("mapped-exclusion", RuleEffect.DENY, ip_network("::ffff:8.8.8.0/120"))
    resolver = Mock()
    resolver.resolve.return_value = DnsRecords((), (IP,))

    with pytest.raises(DestinationDenied) as err:
        resolve(replace(authorization, rules=(*RULES, deny)), resolver)
    assert err.value.scope_reason is ScopeReason.EXCLUDED


def test_dns_failure_returns_a_redacted_reason(authorization):
    resolver = Mock()
    resolver.resolve.side_effect = ResolutionFailure("raw diagnostic")
    with pytest.raises(DestinationDenied, match="^dns_failed$"):
        resolve(authorization, resolver)
