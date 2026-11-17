from unittest.mock import Mock

import requests

from core import recon
from domain.models import FindingType


TARGET = "https://fixture.invalid"


def test_recon_records_http_response(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response.headers["Server"] = "test-fixture"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    send = Mock(return_value=response)
    monkeypatch.setattr(requests.Session, "send", send)

    observation, missing = recon.run(TARGET)

    request = send.call_args.args[0]
    assert request.method == "GET"
    assert request.url == f"{TARGET}/"
    assert send.call_args.kwargs["timeout"] > 0
    assert observation.type == FindingType.INFO
    assert observation.detail == "Status code: 200"
    assert observation.extra["server"] == "test-fixture"
    assert "Strict-Transport-Security" in missing.extra["missing_security_headers"]
    assert "Content-Security-Policy" not in missing.extra["missing_security_headers"]


def test_recon_reports_transport_error(monkeypatch):
    send = Mock(side_effect=requests.ConnectionError("fixture unavailable"))
    monkeypatch.setattr(requests.Session, "send", send)

    finding, = recon.run(TARGET)

    send.assert_called_once()
    assert finding.type == FindingType.ERROR
    assert finding.url == TARGET
    assert finding.detail == "fixture unavailable"
