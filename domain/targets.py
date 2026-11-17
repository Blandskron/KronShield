"""Normalize endpoint inputs and classify the resulting numeric addresses."""

import re
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from urllib.parse import unquote, urlsplit

import idna

from domain.authorization import (
    Address,
    Attribution,
    Network,
    ScopeTarget,
    canonical_address,
    canonical_network,
    validate_dns_name,
)


_AUTHORITY = re.compile(r"(\[[0-9A-Fa-f:.]+\]|[^\[\]:]+)(?::([1-9][0-9]{0,4}))?")
_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_PRIVATE = tuple(ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
_NON_TARGETS = tuple(ip_network(cidr) for cidr in (
    "0.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "168.63.129.16/32", "192.0.0.0/24", "192.0.2.0/24", "192.31.196.0/24",
    "192.52.193.0/24", "192.88.99.0/24", "192.175.48.0/24",
    "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "2001::/23", "2001:db8::/32", "2002::/16", "2620:4f:8000::/48", "3fff::/20", "fd00:ec2::254/128",
))
_IPV6_GLOBAL_UNICAST = IPv6Network("2000::/3")


def canonical_host(value: str) -> str | Address:
    if (
        not isinstance(value, str)
        or not value
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in value for char in "/\\@%?#[]")
    ):
        raise ValueError("Invalid host")
    try:
        address = ip_address(value)
    except ValueError:
        try:
            name = idna.encode(value, uts46=True, std3_rules=True).decode("ascii").removesuffix(".")
        except idna.IDNAError:
            raise ValueError("Invalid DNS name") from None
        validate_dns_name(name)
        return name
    return canonical_address(address)


def canonical_http_target(
    url: str,
    *,
    environment: str,
    attribution: Attribution,
    method: str = "GET",
    third_party_id: str | None = None,
) -> ScopeTarget:
    """Parse an HTTP(S) target without embedded credentials, query or fragment."""
    if (
        not isinstance(url, str)
        or len(url) > 4096
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url)
        or any(char in url for char in "\\?#")
    ):
        raise ValueError("Invalid URL or unsupported URL component")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise ValueError("Invalid URL authority") from None
    authority = _AUTHORITY.fullmatch(parts.netloc)
    if parts.scheme not in {"http", "https"} or authority is None:
        raise ValueError("Expected an absolute HTTP(S) URL")
    hostname, port_text = authority.groups()
    if hostname.startswith("["):
        try:
            host = canonical_address(IPv6Address(hostname[1:-1]))
        except ValueError:
            raise ValueError("Invalid IPv6 URL authority") from None
    else:
        host = canonical_host(hostname)
    port = int(port_text) if port_text is not None else {"http": 80, "https": 443}[parts.scheme]

    raw_path = parts.path or "/"
    if "//" in raw_path or _PERCENT_ESCAPE.search(raw_path):
        raise ValueError("Invalid URL path")
    raw_segments = raw_path.strip("/").split("/") if raw_path != "/" else []
    try:
        path = tuple(unquote(segment, errors="strict") for segment in raw_segments)
    except UnicodeError:
        raise ValueError("Invalid URL path encoding") from None
    return ScopeTarget(
        host=host, environment=environment, attribution=attribution, third_party_id=third_party_id,
        port=port, scheme=parts.scheme, path=path, method=method,
        trailing_slash=bool(path) and raw_path.endswith("/"),
    )


def _in_networks(address: Address, networks: tuple[Network, ...]) -> bool:
    return any(address in network for network in networks)


@dataclass(frozen=True)
class AddressPolicy:
    """Deployment-level restrictions, applied in addition to the audit authorization."""

    private_networks: tuple[Network, ...] = ()
    blocked_networks: tuple[Network, ...] = ()

    def __post_init__(self) -> None:
        private_networks = tuple(self.private_networks)
        blocked_networks = tuple(self.blocked_networks)
        if any(not isinstance(network, (IPv4Network, IPv6Network)) for network in (*private_networks, *blocked_networks)):
            raise ValueError("Expected CIDRs for deployment address policy")
        private_networks = tuple(canonical_network(network) for network in private_networks)
        blocked_networks = tuple(canonical_network(network) for network in blocked_networks)
        if any(not any(
            network.version == private.version and network.subnet_of(private) for private in _PRIVATE
        ) for network in private_networks):
            raise ValueError("Private allowlist requires RFC 1918 or IPv6 ULA subnets")
        object.__setattr__(self, "private_networks", private_networks)
        object.__setattr__(self, "blocked_networks", blocked_networks)

    def permits(self, address: Address) -> bool:
        address = canonical_address(address)
        if _in_networks(address, _NON_TARGETS) or _in_networks(address, self.blocked_networks):
            return False
        if _in_networks(address, _PRIVATE):
            return _in_networks(address, self.private_networks)
        if isinstance(address, IPv6Address) and address not in _IPV6_GLOBAL_UNICAST:
            return False
        return address.is_global and not address.is_multicast and not address.is_reserved
