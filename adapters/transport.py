"""Direct, single-use HTTP/TCP connections to authorized numeric peers."""

import http.client
import io
import socket
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ipaddress import IPv6Address, ip_address
from math import isfinite
from time import monotonic

from application.resolve_target import ResolvedTarget
from application.transport import HttpObservation, TransportFailure, TransportReason
from domain.authorization import Address, ScopeTarget, canonical_address
from domain.budget import BudgetLimits, ExecutionBudget


_HEADER_BYTES = 64 * 1024
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _remaining(deadline: float, budget: ExecutionBudget) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TransportFailure(TransportReason.TIMED_OUT)
    return min(remaining, budget.remaining_seconds())


def _verify_peer(connection: socket.socket, address: Address, port: int) -> None:
    peer = connection.getpeername()
    try:
        peer_address = canonical_address(ip_address(peer[0]))
    except ValueError:
        raise TransportFailure(TransportReason.PEER_MISMATCH) from None
    if peer_address != address or peer[1] != port:
        raise TransportFailure(TransportReason.PEER_MISMATCH)


def _request_parts(target: ScopeTarget) -> tuple[str, str]:
    authority = f"[{target.host}]" if isinstance(target.host, IPv6Address) else str(target.host)
    if target.port != _DEFAULT_PORTS[target.scheme]:
        authority = f"{authority}:{target.port}"
    path = "/" + "/".join(target.path)
    if target.trailing_slash:
        path += "/"
    return authority, path


class _ResponseReader(io.RawIOBase):
    def __init__(self, connection: socket.socket, deadline: float, budget: ExecutionBudget):
        super().__init__()
        self._connection = connection
        self._deadline = deadline
        self._budget = budget
        self.remaining_bytes = _HEADER_BYTES

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        if not self.remaining_bytes:
            raise TransportFailure(TransportReason.WIRE_LIMIT)
        view = memoryview(buffer)
        self._connection.settimeout(_remaining(self._deadline, self._budget))
        count = self._budget.read(
            min(len(view), self.remaining_bytes), lambda size: self._connection.recv_into(view[:size]),
        )
        self.remaining_bytes -= count
        return count

    def makefile(self, mode: str) -> io.BufferedReader:
        # HTTPResponse asks for a buffered binary reader from its socket.
        return io.BufferedReader(self)


class PinnedTransport:
    """Bind a trusted, scope-checking resolver for the job's execution context."""

    def __init__(
        self,
        resolve: Callable[[ScopeTarget], ResolvedTarget],
        *,
        timeout: float = 10,
        max_body_bytes: int = 256 * 1024,
        tls_context: ssl.SSLContext | None = None,
        budget: ExecutionBudget | None = None,
    ):
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("Expected a positive finite transport timeout")
        if type(max_body_bytes) is not int or max_body_bytes < 0:
            raise ValueError("Expected a nonnegative response body byte limit")
        self._resolve = resolve
        self._timeout = timeout
        self._budget = budget if budget is not None else ExecutionBudget(BudgetLimits())
        self._max_body_bytes = min(max_body_bytes, self._budget.limits.max_response_bytes)
        self._tls_context = tls_context if tls_context is not None else ssl.create_default_context()
        if not self._tls_verifies_identity():
            raise ValueError("TLS requires trusted certificates and hostname verification")

    def _tls_verifies_identity(self) -> bool:
        return self._tls_context.check_hostname and self._tls_context.verify_mode == ssl.CERT_REQUIRED

    @contextmanager
    def _open(self, target: ScopeTarget, deadline: float) -> Iterator[tuple[socket.socket, Address]]:
        # Resolve again for each operation. The answer cannot be supplied by a UI
        # or reused by a caller from an earlier authorized connection.
        resolved = self._resolve(target)
        if resolved.target != target or not resolved.addresses:
            raise TransportFailure(TransportReason.INVALID_RESOLUTION)
        try:
            address = canonical_address(resolved.addresses[0])
        except ValueError:
            raise TransportFailure(TransportReason.INVALID_RESOLUTION) from None
        if target.scheme == "https" and not self._tls_verifies_identity():
            raise TransportFailure(TransportReason.TLS_FAILED)
        remaining = _remaining(deadline, self._budget)
        self._budget.charge_attempt()
        family = socket.AF_INET6 if isinstance(address, IPv6Address) else socket.AF_INET
        endpoint = (str(address), target.port, 0, 0) if family == socket.AF_INET6 else (str(address), target.port)
        try:
            with socket.socket(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(remaining)
                connection.connect(endpoint)
                _verify_peer(connection, address, target.port)
                if target.scheme == "https":
                    connection.settimeout(_remaining(deadline, self._budget))
                    with self._tls_context.wrap_socket(connection, server_hostname=str(target.host)) as tls:
                        _verify_peer(tls, address, target.port)
                        yield tls, address
                else:
                    yield connection, address
        except TimeoutError:
            raise TransportFailure(TransportReason.TIMED_OUT) from None
        except ssl.SSLError:
            raise TransportFailure(TransportReason.TLS_FAILED) from None
        except OSError:
            raise TransportFailure(TransportReason.CONNECTION_FAILED) from None

    def http(self, target: ScopeTarget) -> HttpObservation:
        if target.scheme not in _DEFAULT_PORTS or target.method not in {"GET", "HEAD"}:
            raise TransportFailure(TransportReason.INVALID_OPERATION)
        deadline = monotonic() + self._timeout
        authority, path = _request_parts(target)
        request = (
            f"{target.method} {path} HTTP/1.1\r\n"
            f"Host: {authority}\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        with self._budget.operation():
            self._budget.require_bytes(len(request))
            return self._send_http(target, deadline, authority, path, request)

    def _send_http(
        self, target: ScopeTarget, deadline: float, authority: str, path: str, request: bytes,
    ) -> HttpObservation:
        with self._open(target, deadline) as (connection, peer):
            connection.settimeout(_remaining(deadline, self._budget))
            self._budget.charge_write(len(request))
            connection.sendall(request)
            reader = _ResponseReader(connection, deadline, self._budget)
            try:
                with http.client.HTTPResponse(reader, method=target.method) as response:
                    response.begin()
                    status = response.status
                    if 300 <= status < 400:
                        raise TransportFailure(TransportReason.REDIRECT_BLOCKED)
                    if not 200 <= status < 600:
                        raise TransportFailure(TransportReason.INVALID_HTTP)
                    headers = tuple(response.getheaders())
                    body = b""
                    if target.method != "HEAD":
                        encodings = response.headers.get_all("Content-Encoding", [])
                        if any(encoding.strip().lower() != "identity" for encoding in encodings):
                            raise TransportFailure(TransportReason.UNSUPPORTED_ENCODING)
                        length = response.length
                        if length is not None and length > self._max_body_bytes:
                            raise TransportFailure(TransportReason.BODY_TOO_LARGE)
                        reader.remaining_bytes += self._max_body_bytes + 1
                        body = response.read(self._max_body_bytes + 1)
                        if len(body) > self._max_body_bytes:
                            raise TransportFailure(TransportReason.BODY_TOO_LARGE)
                        if length is not None and len(body) != length:
                            raise TransportFailure(TransportReason.INVALID_HTTP)
            except http.client.HTTPException:
                raise TransportFailure(TransportReason.INVALID_HTTP) from None
            _remaining(deadline, self._budget)
        return HttpObservation(f"{target.scheme}://{authority}{path}", peer, status, headers, body)

    def tcp(self, target: ScopeTarget) -> Address:
        if target.scheme is not None or target.port is None:
            raise TransportFailure(TransportReason.INVALID_OPERATION)
        deadline = monotonic() + self._timeout
        with self._budget.operation(), self._open(target, deadline) as (_, peer):
            _remaining(deadline, self._budget)
            return peer
