"""DNS via a deployment-configured recursive resolver."""

from ipaddress import IPv4Address, IPv6Address, ip_address
from math import isfinite
from time import monotonic

import dns.exception
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdataclass
import dns.rdatatype
import dns.resolver

from application.resolve_target import DnsRecords, ResolutionFailure
from domain.authorization import Address, canonical_address, validate_dns_name
from domain.budget import BudgetLimits, ExecutionBudget


class DnsResolver:
    def __init__(
        self, nameservers: tuple[Address, ...], *, timeout: float = 2.0, budget: ExecutionBudget | None = None,
    ):
        servers = tuple(canonical_address(address) for address in nameservers)
        if not servers or not isfinite(timeout) or timeout <= 0:
            raise ValueError("A numeric recursive resolver and a positive finite timeout are required")
        self._nameservers = servers
        self._timeout = timeout
        self._budget = budget if budget is not None else ExecutionBudget(BudgetLimits())

    def _query(self, name: dns.name.Name, record_type: dns.rdatatype.RdataType, deadline: float):
        request = dns.message.make_query(name, record_type)
        for server in self._nameservers:
            remaining = min(deadline - monotonic(), self._budget.remaining_seconds())
            if remaining <= 0:
                raise ResolutionFailure("DNS deadline elapsed")
            self._budget.charge_attempt()
            try:
                response = dns.query.tcp(request, str(server), timeout=remaining)
            except (dns.exception.DNSException, OSError, EOFError):
                continue
            if response.rcode() == dns.rcode.NOERROR:
                return dns.resolver.Answer(name, record_type, dns.rdataclass.IN, response)
            if response.rcode() == dns.rcode.NXDOMAIN:
                raise ResolutionFailure("DNS name does not exist")
        raise ResolutionFailure("DNS lookup failed")

    def resolve(self, host: str) -> DnsRecords:
        validate_dns_name(host)
        name = dns.name.from_text(host, origin=dns.name.root)
        deadline = monotonic() + self._timeout
        chain = None
        addresses: list[Address] = []
        try:
            for record_type, address_type in (
                (dns.rdatatype.A, IPv4Address),
                (dns.rdatatype.AAAA, IPv6Address),
            ):
                answer = self._query(name, record_type, deadline)
                # Both families must observe the same ordered alias chain. NODATA
                # is valid for one family, but timeouts and NXDOMAIN fail closed.
                result = answer.response.resolve_chaining()
                if any(len(rrset) != 1 for rrset in result.cnames):
                    raise ResolutionFailure("Invalid CNAME record set")
                aliases = tuple(rrset[0].target for rrset in result.cnames)
                if chain is not None and aliases != chain:
                    raise ResolutionFailure("Inconsistent DNS aliases")
                chain = aliases
                for record in answer:
                    address = ip_address(record.address)
                    if not isinstance(address, address_type):
                        raise ResolutionFailure("DNS record address family mismatch")
                    addresses.append(address)
        except (dns.exception.DNSException, ValueError) as exc:
            raise ResolutionFailure("DNS lookup failed") from exc
        if not addresses:
            raise ResolutionFailure("Neither address family returned a record")
        return DnsRecords(tuple(alias.to_text() for alias in chain or ()), tuple(addresses))
