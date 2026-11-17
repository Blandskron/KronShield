import socket

import pytest


def _deny_network(*args, **kwargs):
    # Fail outside Exception so a scanner's error handler cannot hide real I/O.
    pytest.fail("Unexpected network I/O. Use a test fixture for the transport.", pytrace=False)


def pytest_configure(config):
    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    patch.setenv("GROQ_API_KEY", "")
    patch.delenv("GROQ_MODEL", raising=False)

    for name in (
        "create_connection", "getaddrinfo", "gethostbyaddr", "gethostbyname",
        "gethostbyname_ex", "getnameinfo",
    ):
        patch.setattr(socket, name, _deny_network)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            patch.setattr(socket.socket, name, _deny_network)
