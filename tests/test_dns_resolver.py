from ipaddress import ip_address
from unittest.mock import Mock

import dns.exception
import dns.message
import dns.rdataclass
import dns.rdatatype
import dns.resolver
import dns.rrset
import pytest

from adapters.dns import DnsResolver
from application.resolve_target import ResolutionFailure


HOST = "scope.example"


def answer(record_type, alias="alias.example.", address=None):
    query = dns.message.make_query(HOST + ".", record_type)
    response = dns.message.make_response(query)
    if alias is not None:
        response.answer.append(dns.rrset.from_text(HOST + ".", 30, "IN", "CNAME", alias))
    if address is not None:
        response.answer.append(dns.rrset.from_text(alias or HOST + ".", 30, "IN", record_type, address))
    parsed = dns.message.from_wire(response.to_wire())
    return dns.resolver.Answer(query.question[0].name, record_type, dns.rdataclass.IN, parsed)


def test_dns_adapter_requests_absolute_a_and_aaaa_from_configured_resolver(monkeypatch):
    adapter = DnsResolver((ip_address("10.20.30.53"),))
    lookup = Mock(side_effect=[
        answer(dns.rdatatype.A, address="8.8.8.8"),
        answer(dns.rdatatype.AAAA, alias="ALIAS.example.", address="2606:4700::1111"),
    ])
    monkeypatch.setattr(adapter._resolver, "resolve", lookup)

    records = adapter.resolve(HOST)

    assert adapter._resolver.nameservers == ["10.20.30.53"]
    assert adapter._resolver.cache is None
    assert [call.args[0].to_text() for call in lookup.call_args_list] == [HOST + ".", HOST + "."]
    assert [call.args[1] for call in lookup.call_args_list] == [dns.rdatatype.A, dns.rdatatype.AAAA]
    assert all(call.kwargs["search"] is False for call in lookup.call_args_list)
    assert all(call.kwargs["raise_on_no_answer"] is False for call in lookup.call_args_list)
    a, aaaa = [call.kwargs["lifetime"] for call in lookup.call_args_list]
    assert 0 < aaaa <= a <= 2
    assert tuple(alias.lower() for alias in records.aliases) == ("alias.example.",)
    assert records.addresses == (ip_address("8.8.8.8"), ip_address("2606:4700::1111"))


def test_dns_adapter_allows_nodata_for_one_family(monkeypatch):
    adapter = DnsResolver((ip_address("10.20.30.53"),))
    lookup = Mock(side_effect=[
        answer(dns.rdatatype.A, address="8.8.8.8"),
        answer(dns.rdatatype.AAAA),
    ])
    monkeypatch.setattr(adapter._resolver, "resolve", lookup)
    assert adapter.resolve(HOST).addresses == (ip_address("8.8.8.8"),)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (answer(dns.rdatatype.AAAA, alias="other.example."), "Inconsistent DNS aliases"),
        (dns.exception.Timeout(), "DNS lookup failed"),
        (dns.resolver.NXDOMAIN(), "DNS lookup failed"),
    ],
)
def test_dns_adapter_does_not_use_partial_or_inconsistent_answers(monkeypatch, reply, message):
    adapter = DnsResolver((ip_address("10.20.30.53"),))
    lookup = Mock(side_effect=[answer(dns.rdatatype.A, address="8.8.8.8"), reply])
    monkeypatch.setattr(adapter._resolver, "resolve", lookup)

    with pytest.raises(ResolutionFailure, match=message):
        adapter.resolve(HOST)


def test_dns_adapter_rejects_ambiguous_cname_rrset(monkeypatch):
    adapter = DnsResolver((ip_address("10.20.30.53"),))
    reply = answer(dns.rdatatype.A, address="8.8.8.8")
    # Inject a malformed set after parsing to exercise the adapter's guard.
    another = dns.rrset.from_text(HOST + ".", 30, "IN", "CNAME", "other.example.")
    reply.response.answer[0].items.update(another.items)
    monkeypatch.setattr(adapter._resolver, "resolve", Mock(return_value=reply))

    with pytest.raises(ResolutionFailure, match="Invalid CNAME record set"):
        adapter.resolve(HOST)
