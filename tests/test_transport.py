import io
import socket
import ssl
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
from ipaddress import ip_address
from unittest.mock import MagicMock, Mock

import pytest

from adapters import transport as adapter
from application.resolve_target import DestinationDenied, DestinationReason, DnsRecords, ResolvedTarget, resolve_target
from application.transport import TransportFailure, TransportReason
from core import recon, scanner
from domain.authorization import Attribution, Authorization, AuthorizationStatus, RuleEffect, ScopeRule, ScopeTarget
from domain.targets import AddressPolicy, canonical_http_target


IP = ip_address("8.8.8.8")
IPV6 = ip_address("2606:4700::1111")
OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
TARGET = canonical_http_target(
    "http://scope.example:8080/api/status/", environment="lab", attribution=Attribution.FIRST_PARTY,
)


def fake_socket(reply=OK, *, peer=(str(IP), 8080)):
    source = io.BytesIO(reply)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.getpeername.return_value = peer

    def receive(buffer):
        return source.readinto(buffer)

    connection.recv_into.side_effect = receive
    return connection


def pinned_resolver(address=IP):
    return Mock(side_effect=lambda target: ResolvedTarget(target, (), (address,)))


@pytest.fixture
def socket_factory(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(socket, "socket", factory)
    return factory


def test_http_uses_numeric_ip_and_sends_original_host_and_path_without_proxy(socket_factory, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:8888")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:8888")
    connection = fake_socket()
    socket_factory.return_value = connection
    resolve = pinned_resolver()

    result = adapter.PinnedTransport(resolve).http(TARGET)

    resolve.assert_called_once_with(TARGET)
    socket_factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
    connection.connect.assert_called_once_with((str(IP), 8080))
    connection.sendall.assert_called_once_with(
        b"GET /api/status/ HTTP/1.1\r\nHost: scope.example:8080\r\n"
        b"Accept-Encoding: identity\r\nConnection: close\r\n\r\n"
    )
    connection.__exit__.assert_called_once()
    assert (result.peer, result.status, result.body) == (IP, 200, b"ok")
    assert result.url == "http://scope.example:8080/api/status/"


def test_https_verifies_peer_and_uses_original_hostname_for_tls(socket_factory, monkeypatch):
    target = replace(TARGET, scheme="https", port=443)
    connection = fake_socket(peer=(str(IP), 443))
    secured = fake_socket(peer=(str(IP), 443))
    socket_factory.return_value = connection
    context = ssl.create_default_context()
    wrap = Mock(return_value=secured)
    monkeypatch.setattr(context, "wrap_socket", wrap)

    result = adapter.PinnedTransport(pinned_resolver(), tls_context=context).http(target)

    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    connection.connect.assert_called_once_with((str(IP), 443))
    connection.getpeername.assert_called_once()
    secured.getpeername.assert_called_once()
    wrap.assert_called_once_with(connection, server_hostname="scope.example")
    connection.sendall.assert_not_called()
    assert b"Host: scope.example\r\n" in secured.sendall.call_args.args[0]
    assert result.url == "https://scope.example/api/status/"


def test_tls_certificate_error_stops_before_http(socket_factory, monkeypatch):
    connection = fake_socket(peer=(str(IP), 443))
    socket_factory.return_value = connection
    context = ssl.create_default_context()
    wrap = Mock(side_effect=ssl.SSLCertVerificationError("untrusted certificate"))
    monkeypatch.setattr(context, "wrap_socket", wrap)

    with pytest.raises(TransportFailure, match="^tls_failed$"):
        adapter.PinnedTransport(pinned_resolver(), tls_context=context).http(replace(TARGET, scheme="https", port=443))

    wrap.assert_called_once()
    connection.sendall.assert_not_called()
    connection.__exit__.assert_called_once()


def test_http_data_is_never_sent_to_a_mismatched_tls_peer(socket_factory, monkeypatch):
    socket_factory.return_value = fake_socket(peer=(str(IP), 443))
    secured = fake_socket(peer=("127.0.0.1", 443))
    context = ssl.create_default_context()
    monkeypatch.setattr(context, "wrap_socket", Mock(return_value=secured))
    transport = adapter.PinnedTransport(pinned_resolver(), tls_context=context)

    with pytest.raises(TransportFailure, match="^peer_mismatch$"):
        transport.http(replace(TARGET, scheme="https", port=443))

    secured.sendall.assert_not_called()
    secured.__exit__.assert_called_once()


def test_transport_rejects_insecure_tls_configuration():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="hostname verification"):
        adapter.PinnedTransport(pinned_resolver(), tls_context=context)


@pytest.mark.parametrize("peer", [("127.0.0.1", 8080), (str(IP), 9999)])
def test_peer_ip_and_port_are_verified_before_sending_http(socket_factory, peer):
    socket_factory.return_value = fake_socket(peer=peer)

    with pytest.raises(TransportFailure, match="^peer_mismatch$"):
        adapter.PinnedTransport(pinned_resolver()).http(TARGET)

    socket_factory.return_value.sendall.assert_not_called()
    socket_factory.return_value.__exit__.assert_called_once()


def test_redirect_cannot_connect_to_canary(socket_factory):
    connection = fake_socket(
        b"HTTP/1.1 302 Found\r\nLocation: http://169.254.169.254/latest/\r\nContent-Length: 0\r\n\r\n"
    )
    socket_factory.return_value = connection
    resolve = pinned_resolver()

    with pytest.raises(TransportFailure, match="^redirect_blocked$"):
        adapter.PinnedTransport(resolve).http(TARGET)

    resolve.assert_called_once_with(TARGET)
    socket_factory.assert_called_once()
    connection.connect.assert_called_once_with((str(IP), 8080))


def test_dns_is_rechecked_and_rebinding_cannot_open_another_socket(socket_factory):
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    authorization = Authorization(
        "auth", 1, "org", "project", "owner", "proof", "a" * 64, AuthorizationStatus.APPROVED,
        now - timedelta(minutes=1), now + timedelta(minutes=1), "lab", frozenset({"web"}),
        (ScopeRule("name", RuleEffect.ALLOW, TARGET.host), ScopeRule("ip", RuleEffect.ALLOW, IP)), "reviewer",
    )
    resolver = Mock()
    resolver.resolve.side_effect = [DnsRecords((), (IP,)), DnsRecords((), (ip_address("127.0.0.1"),))]
    verify = partial(
        resolve_target, authorization=authorization, organization_id="org", project_id="project", technique="web",
        clock=lambda: now, resolver=resolver, address_policy=AddressPolicy(),
        lookup_attribution=lambda host: (Attribution.FIRST_PARTY, None),
    )
    connection = fake_socket()
    socket_factory.return_value = connection
    transport = adapter.PinnedTransport(verify)

    assert transport.http(TARGET).peer == IP
    with pytest.raises(DestinationDenied) as error:
        transport.http(TARGET)

    assert error.value.reason is DestinationReason.ADDRESS_BLOCKED
    assert resolver.resolve.call_count == 2
    socket_factory.assert_called_once()
    connection.connect.assert_called_once_with((str(IP), 8080))


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (b"HTTP/1.1 200 OK\r\nContent-Length: 999\r\n\r\n", TransportReason.BODY_TOO_LARGE),
        (b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nabc", TransportReason.BODY_TOO_LARGE),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n0\r\n\r\n", TransportReason.BODY_TOO_LARGE),
        (b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n", TransportReason.UNSUPPORTED_ENCODING),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\na", TransportReason.INVALID_HTTP),
        (b"garbage\r\n\r\n", TransportReason.INVALID_HTTP),
        (b"HTTP/1.1 200 OK\r\nA: " + b"x" * (64 * 1024), TransportReason.WIRE_LIMIT),
    ],
    ids=["content-length", "close-delimited", "chunked", "encoding", "truncated", "status", "headers"],
)
def test_http_limits_oversize_and_invalid_responses(socket_factory, reply, reason):
    socket_factory.return_value = fake_socket(reply)

    with pytest.raises(TransportFailure) as error:
        adapter.PinnedTransport(pinned_resolver(), max_body_bytes=2).http(TARGET)

    assert error.value.reason is reason
    socket_factory.return_value.__exit__.assert_called_once()


def test_exact_body_budget_and_head_metadata(socket_factory):
    socket_factory.side_effect = [
        fake_socket(OK),
        fake_socket(b"HTTP/1.1 200 OK\r\nContent-Length: 9999\r\n\r\n"),
    ]
    transport = adapter.PinnedTransport(pinned_resolver(), max_body_bytes=2)
    assert transport.http(TARGET).body == b"ok"
    assert transport.http(replace(TARGET, method="HEAD")).body == b""


def test_slow_headers_cannot_extend_absolute_deadline(socket_factory, monkeypatch):
    tick = Mock(return_value=100.0)
    monkeypatch.setattr(adapter, "monotonic", tick)
    connection = fake_socket()
    socket_factory.return_value = connection

    def receive(buffer):
        buffer[:1] = b"H"
        tick.return_value = 111.0
        return 1

    connection.recv_into.side_effect = receive
    with pytest.raises(TransportFailure, match="^timed_out$"):
        adapter.PinnedTransport(pinned_resolver(), timeout=10).http(TARGET)

    connection.recv_into.assert_called_once()


def test_tcp_probe_uses_only_one_authorized_ipv6_endpoint(socket_factory):
    connection = fake_socket(peer=(str(IPV6), 22, 0, 0))
    socket_factory.return_value = connection
    target = ScopeTarget("scope.example", "lab", Attribution.FIRST_PARTY, port=22)
    transport = adapter.PinnedTransport(pinned_resolver(IPV6))

    finding = scanner.scan_authorized_port(target, transport)

    socket_factory.assert_called_once_with(socket.AF_INET6, socket.SOCK_STREAM)
    connection.connect.assert_called_once_with((str(IPV6), 22, 0, 0))
    connection.sendall.assert_not_called()
    assert finding.extra == {"port": 22, "status": "open", "peer": str(IPV6)}


def test_ipv6_http_literal_keeps_brackets_in_host_header(socket_factory):
    connection = fake_socket(peer=(str(IPV6), 8080, 0, 0))
    socket_factory.return_value = connection
    target = replace(TARGET, host=IPV6)
    result = adapter.PinnedTransport(pinned_resolver(IPV6)).http(target)

    assert b"Host: [2606:4700::1111]:8080\r\n" in connection.sendall.call_args.args[0]
    assert result.url == "http://[2606:4700::1111]:8080/api/status/"


def test_authorized_recon_reports_only_selected_headers(socket_factory):
    socket_factory.return_value = fake_socket(
        b"HTTP/1.1 200 OK\r\nServer: canary\r\nSet-Cookie: password=secret\r\nContent-Length: 0\r\n\r\n"
    )
    observation, _ = recon.run_authorized(TARGET, adapter.PinnedTransport(pinned_resolver()))
    assert observation.extra == {"server": "canary", "headers": {"Server": "canary"}}


def test_invalid_method_or_mismatched_resolution_fails_before_connecting(socket_factory):
    resolve = Mock(return_value=ResolvedTarget(replace(TARGET, host="other.example"), (), (IP,)))
    transport = adapter.PinnedTransport(resolve)

    with pytest.raises(TransportFailure, match="^invalid_operation$"):
        transport.http(replace(TARGET, method="POST"))
    resolve.assert_not_called()
    with pytest.raises(TransportFailure, match="^invalid_resolution$"):
        transport.http(TARGET)
    socket_factory.assert_not_called()


def test_typed_http_target_cannot_bypass_url_path_validation():
    with pytest.raises(ValueError, match="canonical path"):
        replace(TARGET, path=("..;", "admin"))
    with pytest.raises(ValueError, match="nonempty HTTP path"):
        replace(TARGET, path=iter(()))
