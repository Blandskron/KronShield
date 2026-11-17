from ipaddress import ip_address, ip_network

import pytest

from domain.authorization import Attribution
from domain.targets import AddressPolicy, canonical_http_target


def parse(url):
    return canonical_http_target(url, environment="lab", attribution=Attribution.FIRST_PARTY)


def test_http_target_has_idna_host_effective_port_and_canonical_path():
    target = parse("HTTPS://Bücher.Example./api/%73tatus/")

    assert (target.host, target.scheme, target.port, target.method) == ("xn--bcher-kva.example", "https", 443, "GET")
    assert target.path == ("api", "status")
    assert target.trailing_slash
    assert parse("http://lab-http").port == 80
    assert parse("http://lab-http").path == ()


@pytest.mark.parametrize(
    ("url", "ip", "port"),
    [
        ("https://8.8.8.8", "8.8.8.8", 443),
        ("http://[2606:4700:0:0::1111]:8080", "2606:4700::1111", 8080),
        ("http://[::ffff:8.8.8.8]", "8.8.8.8", 80),
    ],
)
def test_literal_ips_are_typed_and_mapped_ipv6_is_ipv4(url, ip, port):
    target = parse(url)
    assert target.host == ip_address(ip)
    assert target.port == port


@pytest.mark.parametrize("url", [
    "//service.example",
    "ftp://service.example",
    "https:///service.example",
    "https://user:secret@service.example",
    "https://user%40service.example",
    "https://service.example/?token=secret",
    "https://service.example/?",
    "https://service.example/#",
    "https://service.example/#token=secret",
    " https://service.example",
    "https://service.exam\nple",
    "https://service.example\\@other.example",
    "https://service.example:",
    "https://service.example:0",
    "https://service.example:0443",
    "https://service.example:65536",
    "https://service.example%2fother.example",
    "https://service.example：443",
    "https://service.example..",
    "http://127.1",
    "http://127.0.00.1",
    "http://2130706433",
    "http://0x7f000001",
    "http://017700000001",
    "http://7f.0.0.0x01",
    "http://127.0.0.1.",
    "http://１２７.０.０.１",
    "http://lab.localhost",
    "http://[::1%25eth0]",
    "http://[v1.fe80]",
    "http://[8.8.8.8]",
    "http://2606:4700::1111",
    "https://service.example/a//b",
    "https://service.example/a/%2fadmin",
    "https://service.example/a/%5cadmin",
    "https://service.example/a/%252fadmin",
    "https://service.example/a/%2e%2e/admin",
    "https://service.example/a/../admin",
    "https://service.example/a;param",
    "https://service.example/a%3bparam",
    "https://service.example/%",
    "https://service.example/%C0%AF",
])
def test_ambiguous_or_credential_bearing_urls_are_rejected(url):
    with pytest.raises(ValueError) as error:
        parse(url)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("value", [
    "0.0.0.0", "127.0.0.1", "169.254.169.254", "168.63.129.16", "100.100.100.200", "192.0.0.9",
    "192.0.2.10", "198.18.0.5", "224.0.0.1", "255.255.255.255",
    "::", "::1", "::ffff:169.254.169.254", "fd00:ec2::254", "fe80::1", "ff02::1",
    "2001:db8::1", "2002:7f00:1::1", "64:ff9b::7f00:1", "3fff::1",
])
def test_special_addresses_are_blocked_even_with_private_networks_configured(value):
    policy = AddressPolicy(private_networks=(ip_network("fd00::/8"), ip_network("10.0.0.0/8")))
    assert not policy.permits(ip_address(value))


def test_private_ranges_require_a_deployment_allowlist_and_block_rules_win():
    permitted = ip_address("10.20.30.2")
    policy = AddressPolicy(
        private_networks=(ip_network("10.20.30.0/24"), ip_network("fd20::/48")),
        blocked_networks=(ip_network("10.20.30.1/32"), ip_network("::ffff:8.8.8.0/120")),
    )

    assert not AddressPolicy().permits(permitted)
    assert policy.permits(permitted)
    assert policy.permits(ip_address("fd20::4"))
    assert policy.permits(ip_address("2606:4700::1111"))
    assert not policy.permits(ip_address("10.20.30.1"))
    assert not policy.permits(ip_address("10.20.31.2"))
    assert not policy.permits(ip_address("8.8.8.8"))
    with pytest.raises(ValueError, match="Private allowlist"):
        AddressPolicy(private_networks=(ip_network("0.0.0.0/0"),))
