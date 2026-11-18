from ipaddress import ip_address
from unittest.mock import Mock

import dns.exception
import dns.message
import dns.rdatatype
import dns.rrset
import pytest

from adapters.dns import DnsResolver
from application.resolve_target import ResolutionFailure
from domain.budget import BudgetExceeded, BudgetLimits, BudgetReason, ExecutionBudget


HOST = "scope.example"


def answer(record_type, alias="alias.example.", address=None):
    query = dns.message.make_query(HOST + ".", record_type)
    response = dns.message.make_response(query)
    if alias is not None:
        response.answer.append(dns.rrset.from_text(HOST + ".", 30, "IN", "CNAME", alias))
    if address is not None:
        response.answer.append(dns.rrset.from_text(alias or HOST + ".", 30, "IN", record_type, address))
    return dns.message.from_wire(response.to_wire())


def test_dns_adapter_requests_absolute_a_and_aaaa_from_configured_resolver(monkeypatch):
    adapter = DnsResolver((ip_address("10.20.30.53"),))
    lookup = Mock(side_effect=[
        answer(dns.rdatatype.A, address="8.8.8.8"),
        answer(dns.rdatatype.AAAA, alias="ALIAS.example.", address="2606:4700::1111"),
    ])
    monkeypatch.setattr("dns.query.tcp", lookup)

    records = adapter.resolve(HOST)

    assert [call.args[1] for call in lookup.call_args_list] == ["10.20.30.53", "10.20.30.53"]
    questions = [call.args[0].question[0] for call in lookup.call_args_list]
    assert [question.name.to_text() for question in questions] == [HOST + ".", HOST + "."]
    assert [question.rdtype for question in questions] == [dns.rdatatype.A, dns.rdatatype.AAAA]
    a, aaaa = [call.kwargs["timeout"] for call in lookup.call_args_list]
    assert 0 < aaaa <= a <= 2
    assert tuple(alias.lower() for alias in records.aliases) == ("alias.example.",)
    assert records.addresses == (ip_address("8.8.8.8"), ip_address("2606:4700::1111"))


def test_dns_adapter_allows_nodata_for_one_family(monkeypatch):
    adapter = DnsResolver((ip_address("10.20.30.53"),))
    lookup = Mock(side_effect=[
        answer(dns.rdatatype.A, address="8.8.8.8"),
        answer(dns.rdatatype.AAAA),
    ])
    monkeypatch.setattr("dns.query.tcp", lookup)
    assert adapter.resolve(HOST).addresses == (ip_address("8.8.8.8"),)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (answer(dns.rdatatype.AAAA, alias="other.example."), "Inconsistent DNS aliases"),
        (dns.exception.Timeout(), "DNS lookup failed"),
    ],
)
def test_dns_adapter_does_not_use_partial_or_inconsistent_answers(monkeypatch, reply, message):
    adapter = DnsResolver((ip_address("10.20.30.53"),))
    lookup = Mock(side_effect=[answer(dns.rdatatype.A, address="8.8.8.8"), reply])
    monkeypatch.setattr("dns.query.tcp", lookup)

    with pytest.raises(ResolutionFailure, match=message):
        adapter.resolve(HOST)


def test_dns_adapter_fails_closed_on_nxdomain_after_a_answer(monkeypatch):
    reply = answer(dns.rdatatype.AAAA, alias=None)
    reply.set_rcode(dns.rcode.NXDOMAIN)
    monkeypatch.setattr("dns.query.tcp", Mock(side_effect=[answer(dns.rdatatype.A, address="8.8.8.8"), reply]))

    with pytest.raises(ResolutionFailure, match="DNS name does not exist"):
        DnsResolver((ip_address("10.20.30.53"),)).resolve(HOST)


def test_dns_adapter_rejects_ambiguous_cname_rrset(monkeypatch):
    adapter = DnsResolver((ip_address("10.20.30.53"),))
    reply = answer(dns.rdatatype.A, address="8.8.8.8")
    # Inject a malformed set after parsing to exercise the adapter's guard.
    another = dns.rrset.from_text(HOST + ".", 30, "IN", "CNAME", "other.example.")
    reply.answer[0].items.update(another.items)
    monkeypatch.setattr("dns.query.tcp", Mock(return_value=reply))

    with pytest.raises(ResolutionFailure, match="Invalid CNAME record set"):
        adapter.resolve(HOST)


def test_dns_attempt_budget_includes_recursors_that_failed_to_answer(monkeypatch):
    budget = ExecutionBudget(BudgetLimits(max_operations=2))
    adapter = DnsResolver((ip_address("10.20.30.53"), ip_address("10.20.30.54")), budget=budget)
    lookup = Mock(side_effect=[dns.exception.Timeout(), answer(dns.rdatatype.A, address="8.8.8.8")])
    monkeypatch.setattr("dns.query.tcp", lookup)

    with pytest.raises(BudgetExceeded) as error:
        adapter.resolve(HOST)

    assert error.value.reason is BudgetReason.OPERATIONS
    assert budget.usage().operations == 2
    assert [call.args[1] for call in lookup.call_args_list] == ["10.20.30.53", "10.20.30.54"]
