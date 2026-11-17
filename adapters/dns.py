"""DNS via a deployment-configured recursive resolver."""

from ipaddress import IPv4Address, IPv6Address, ip_address
from math import isfinite
from time import monotonic

import dns.exception
import dns.name
import dns.rdatatype
import dns.resolver

from application.resolve_target import DnsRecords, ResolutionFailure
from domain.authorization import Address, canonical_address, validate_dns_name


class DnsResolver:
    def __init__(self, nameservers: tuple[Address, ...], *, timeout: float = 2.0):
        servers = tuple(canonical_address(address) for address in nameservers)
        if not servers or not isfinite(timeout) or timeout <= 0:
            raise ValueError("A numeric recursive resolver and a positive finite timeout are required")
        self._resolver = dns.resolver.Resolver(configure=False)
        self._resolver.nameservers = [str(address) for address in servers]
        self._timeout = timeout

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
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ResolutionFailure("DNS deadline elapsed")
                answer = self._resolver.resolve(
                    name, record_type, search=False, lifetime=remaining, raise_on_no_answer=False,
                )
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
