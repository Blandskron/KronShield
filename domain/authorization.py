"""Immutable scope records for already normalized targets."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network


Address = IPv4Address | IPv6Address
Network = IPv4Network | IPv6Network
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_METHOD = re.compile(r"[A-Z][A-Z0-9-]*")


def _required_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")


def utc_instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Expected a timezone-aware timestamp")
    return value.astimezone(timezone.utc)


def _validate_name(host: str) -> None:
    # URL parsing and IDNA conversion belong to the target adapter.
    labels = host.split(".")
    if (
        len(host) > 253
        or not all(_HOST_LABEL.fullmatch(label) for label in labels)
        or not any(char.isalpha() for char in labels[-1])
    ):
        raise ValueError("Expected a canonical DNS name or a typed IP address")


def _validate_port(port: int) -> None:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Port must be an integer between 1 and 65535")


def _path_segments(value: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError("Expected a sequence of canonical path segments")
    segments = tuple(value)
    for segment in segments:
        if (
            not isinstance(segment, str)
            or segment in {"", ".", ".."}
            or any(char in segment for char in "/\\%?#")
            or any(ord(char) <= 32 or ord(char) == 127 for char in segment)
        ):
            raise ValueError("Expected canonical path segments")
    return segments


def _technique_ids(value: frozenset[str]) -> frozenset[str]:
    if isinstance(value, (str, bytes)):
        raise ValueError("Expected a collection of technique IDs")
    techniques = frozenset(value)
    for technique in techniques:
        _required_text(technique, "technique")
    return techniques


class AuthorizationStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REVOKED = "revoked"


class Attribution(str, Enum):
    FIRST_PARTY = "first_party"
    THIRD_PARTY = "third_party"
    SHARED = "shared"
    UNKNOWN = "unknown"


class RuleEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class ScopeTarget:
    """Inventory attribution with a canonical destination and optional HTTP request."""

    host: str | Address
    environment: str
    attribution: Attribution
    third_party_id: str | None = None
    port: int | None = None
    scheme: str | None = None
    path: tuple[str, ...] | None = None
    method: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.host, str):
            _validate_name(self.host)
        elif not isinstance(self.host, (IPv4Address, IPv6Address)):
            raise ValueError("Expected a canonical DNS name or a typed IP address")
        _required_text(self.environment, "environment")
        if not isinstance(self.attribution, Attribution):
            raise ValueError("Expected a known attribution category")
        if self.attribution in {Attribution.THIRD_PARTY, Attribution.SHARED}:
            _required_text(self.third_party_id, "third_party_id")
        elif self.third_party_id is not None:
            raise ValueError("Third-party identity requires third-party or shared attribution")
        if self.port is not None:
            _validate_port(self.port)
        if self.scheme is None:
            if self.path is not None or self.method is not None:
                raise ValueError("Path and method require an HTTP scheme")
            return
        if self.scheme not in {"http", "https"} or self.port is None or self.path is None:
            raise ValueError("HTTP targets require a scheme, effective port and path")
        if not isinstance(self.method, str) or not _METHOD.fullmatch(self.method):
            raise ValueError("HTTP targets require a canonical method")
        object.__setattr__(self, "path", _path_segments(self.path))


@dataclass(frozen=True)
class ScopeRule:
    """A positive or negative match against a canonical destination."""

    id: str
    effect: RuleEffect
    destination: str | Address | Network
    subdomains: bool = False
    ports: frozenset[int] = frozenset()
    scheme: str | None = None
    path_prefix: tuple[str, ...] | None = None
    methods: frozenset[str] = frozenset()
    techniques: frozenset[str] = frozenset()
    attribution: Attribution | None = None
    third_party_id: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.id, "rule id")
        if not isinstance(self.effect, RuleEffect) or type(self.subdomains) is not bool:
            raise ValueError("Invalid scope rule effect or subdomains flag")
        if isinstance(self.destination, str):
            _validate_name(self.destination)
        elif self.subdomains or not isinstance(
            self.destination, (IPv4Address, IPv6Address, IPv4Network, IPv6Network)
        ):
            raise ValueError("Expected a DNS name, IP address or CIDR")
        if self.attribution is not None and not isinstance(self.attribution, Attribution):
            raise ValueError("Expected a known attribution category")
        if self.attribution in {Attribution.THIRD_PARTY, Attribution.SHARED}:
            _required_text(self.third_party_id, "third_party_id")
        elif self.third_party_id is not None:
            raise ValueError("Third-party identity requires third-party or shared attribution")
        if self.scheme not in {None, "http", "https"}:
            raise ValueError("Invalid HTTP scheme")

        ports = frozenset(self.ports)
        for port in ports:
            _validate_port(port)
        object.__setattr__(self, "ports", ports)
        if isinstance(self.methods, (str, bytes)):
            raise ValueError("Expected a collection of HTTP methods")
        methods = frozenset(self.methods)
        if any(not isinstance(method, str) or not _METHOD.fullmatch(method) for method in methods):
            raise ValueError("Expected canonical HTTP methods")
        object.__setattr__(self, "methods", methods)
        object.__setattr__(self, "techniques", _technique_ids(self.techniques))
        if self.path_prefix is not None:
            object.__setattr__(self, "path_prefix", _path_segments(self.path_prefix))

    def matches(self, target: ScopeTarget) -> bool:
        host = target.host
        if isinstance(self.destination, (IPv4Network, IPv6Network)):
            if not isinstance(host, (IPv4Address, IPv6Address)) or host not in self.destination:
                return False
        elif self.subdomains:
            if not isinstance(host, str) or not host.endswith("." + self.destination):
                return False
        elif host != self.destination:
            return False

        if self.ports and target.port not in self.ports:
            return False
        if self.scheme is not None and self.scheme != target.scheme:
            return False
        if self.methods and target.method not in self.methods:
            return False
        if self.path_prefix is not None:
            return target.path is not None and target.path[:len(self.path_prefix)] == self.path_prefix
        return True

    def matches_attribution(self, target: ScopeTarget) -> bool:
        if self.attribution is None:
            return self.effect is RuleEffect.DENY or target.attribution is Attribution.FIRST_PARTY
        return (self.attribution, self.third_party_id) == (target.attribution, target.third_party_id)


@dataclass(frozen=True)
class Authorization:
    id: str
    revision: int
    organization_id: str
    project_id: str
    delegator_id: str
    document_reference: str
    document_sha256: str
    status: AuthorizationStatus
    valid_from: datetime
    valid_until: datetime
    environment: str
    techniques: frozenset[str]
    rules: tuple[ScopeRule, ...]
    verified_by: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "id", "organization_id", "project_id", "delegator_id", "document_reference", "environment"
        ):
            _required_text(getattr(self, field), field)
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("Authorization revision must be a positive integer")
        if not isinstance(self.document_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.document_sha256
        ):
            raise ValueError("Expected the lowercase SHA-256 of the authorization document")
        if not isinstance(self.status, AuthorizationStatus):
            raise ValueError("Expected a known authorization status")
        if self.status is AuthorizationStatus.APPROVED or self.verified_by is not None:
            _required_text(self.verified_by, "verified_by")

        start = utc_instant(self.valid_from)
        end = utc_instant(self.valid_until)
        if start >= end:
            raise ValueError("Authorization window must have a positive duration")
        object.__setattr__(self, "valid_from", start)
        object.__setattr__(self, "valid_until", end)

        object.__setattr__(self, "techniques", _technique_ids(self.techniques))
        rules = tuple(self.rules)
        if any(not isinstance(rule, ScopeRule) for rule in rules):
            raise ValueError("Expected scope rules")
        if len({rule.id for rule in rules}) != len(rules):
            raise ValueError("Scope rule IDs must be unique per revision")
        object.__setattr__(self, "rules", rules)
