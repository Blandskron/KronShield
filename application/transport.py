"""Bounded audit operations exposed by the transport adapter."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from domain.authorization import Address, ScopeTarget


class TransportReason(str, Enum):
    INVALID_OPERATION = "invalid_operation"
    INVALID_RESOLUTION = "invalid_resolution"
    PEER_MISMATCH = "peer_mismatch"
    CONNECTION_FAILED = "connection_failed"
    TLS_FAILED = "tls_failed"
    TIMED_OUT = "timed_out"
    INVALID_HTTP = "invalid_http"
    REDIRECT_BLOCKED = "redirect_blocked"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    BODY_TOO_LARGE = "body_too_large"
    WIRE_LIMIT = "wire_limit"


class TransportFailure(Exception):
    def __init__(self, reason: TransportReason):
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True)
class HttpObservation:
    url: str
    peer: Address
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class SafeTransport(Protocol):
    def http(self, target: ScopeTarget) -> HttpObservation: ...

    def tcp(self, target: ScopeTarget) -> Address: ...
