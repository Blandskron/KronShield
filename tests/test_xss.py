from unittest.mock import Mock

import requests

from core import xss
from domain.models import FindingType
from gpt import client


TARGET = "https://fixture.invalid/search"


def test_xss_records_a_reflected_payload(monkeypatch):
    payload = "test-marker"
    generate_payloads = Mock(return_value=[payload])
    monkeypatch.setattr(client, "generate_payloads", generate_payloads)
    response = requests.Response()
    response.status_code = 200
    response._content = payload.encode()
    send = Mock(return_value=response)
    monkeypatch.setattr(requests.Session, "send", send)

    finding, = xss.test(TARGET)

    generate_payloads.assert_called_once()
    assert send.call_args.args[0].url == f"{TARGET}?q={payload}"
    assert finding.type == FindingType.XSS
    assert finding.payload == payload


def test_xss_uses_fallback_and_reports_transport_error(monkeypatch):
    monkeypatch.setattr(client, "generate_payloads", Mock(return_value=[]))
    monkeypatch.setattr(
        xss.settings, "load", lambda: {"xss_payloads": ["fallback-marker"]}
    )
    send = Mock(side_effect=requests.ConnectionError("fixture unavailable"))
    monkeypatch.setattr(requests.Session, "send", send)

    finding, = xss.test(TARGET)

    send.assert_called_once()
    assert finding.type == FindingType.ERROR
    assert finding.payload == "fallback-marker"
    assert "fixture unavailable" in finding.detail
