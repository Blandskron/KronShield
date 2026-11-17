import socket
from unittest.mock import Mock, call

from core import scanner
from domain.models import FindingType


def test_scanner_records_only_open_ports_and_closes_socket(monkeypatch):
    connection = Mock(spec=socket.socket)
    connect = Mock(side_effect=[ConnectionRefusedError(), connection])
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(scanner.settings, "ports_to_scan", lambda: [80, 443])

    finding, = scanner.scan_ports("https://fixture.invalid")

    assert connect.call_args_list == [
        call(("fixture.invalid", 80), timeout=2),
        call(("fixture.invalid", 443), timeout=2),
    ]
    connection.close.assert_called_once_with()
    assert finding.type == FindingType.PORT
    assert finding.extra == {"port": 443, "status": "open"}
