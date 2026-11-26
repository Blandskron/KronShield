import _socket
import asyncio
import json
import socket
import sys

import httpx
import pytest

from application.analysis_proposals import ProposalBudgetExceeded, ProposalDependencyMissing
from infra import local_inference
from infra.local_inference import LocalProposalProvider


_socketpair = socket.socketpair


@pytest.fixture(autouse=True)
def windows_asyncio_wakeup_socket(monkeypatch):
    if sys.platform != "win32":
        return

    def open_wakeup_pair(*args, **kwargs):
        # Python 3.10 implements the event loop's socketpair with a local TCP handshake on Windows.
        with monkeypatch.context() as setup:
            setup.setattr(socket.socket, "connect", _socket.socket.connect)
            return _socketpair(*args, **kwargs)

    monkeypatch.setattr(socket, "socketpair", open_wakeup_pair)


def complete(handler, *, input_limit=8, output_limit=20, byte_limit=100):
    provider = LocalProposalProvider(httpx.MockTransport(handler))
    return provider.complete("instrucciones", b'{"evidence":[]}', input_token_limit=input_limit,
                             output_token_limit=output_limit, output_byte_limit=byte_limit)


def response(data):
    return httpx.Response(200, stream=httpx.ByteStream(json.dumps(data).encode()))


@pytest.fixture
def exchange():
    return {
        "/apply-template": {"prompt": "formatted"},
        "/tokenize": {"tokens": [1, 2, 3]},
        "/completion": {"content": '{"kind":"abstain"}', "tokens_evaluated": 3,
                        "tokens_predicted": 7, "truncated": False, "stop_type": "eos"},
    }


def test_adapter_uses_fixed_internal_origin_and_passes_only_minimal_data(exchange):
    requests = {}

    def handle(request):
        assert request.method == "POST"
        assert request.url.host == "inference" and request.url.port == 8080
        assert "authorization" not in request.headers
        requests[request.url.path] = json.loads(request.content)
        return response(exchange[request.url.path])

    reply = complete(handle)
    assert list(requests) == list(exchange)
    assert requests["/apply-template"] == {"messages": [
        {"role": "system", "content": "instrucciones"}, {"role": "user", "content": '{"evidence":[]}'},
    ]}
    assert requests["/tokenize"] == {"content": "formatted", "add_special": True}
    completion = requests["/completion"]
    assert completion["prompt"] == [1, 2, 3]
    assert completion["n_predict"] == 20 and completion["cache_prompt"] is False
    assert "json_schema" in completion and "tools" not in completion
    assert (reply.body, reply.input_tokens, reply.output_tokens) == (b'{"kind":"abstain"}', 3, 7)


@pytest.mark.parametrize(("input_limit", "output_limit"), [(2, 20), (8, 2046)])
def test_preflight_blocks_generation_if_token_budget_cannot_fit(exchange, input_limit, output_limit):
    def handle(request):
        assert request.url.path != "/completion"
        return response(exchange[request.url.path])

    with pytest.raises(ProposalBudgetExceeded):
        complete(handle, input_limit=input_limit, output_limit=output_limit)


def test_missing_runtime_is_explicit():
    def disconnected(request):
        raise httpx.ConnectError("private connection detail", request=request)

    with pytest.raises(ProposalDependencyMissing):
        complete(disconnected)
    with pytest.raises(ProposalDependencyMissing):
        complete(lambda _: httpx.Response(503))


def test_no_redirect_is_followed():
    def handle(request):
        assert request.url.path == "/apply-template"
        return httpx.Response(307, headers={"Location": "https://example.invalid/"})

    with pytest.raises(httpx.HTTPStatusError):
        complete(handle)


def test_entire_request_sequence_has_a_single_deadline(monkeypatch, exchange):
    monkeypatch.setattr(local_inference, "TIMEOUT_SECONDS", 0.05)

    async def handle(request):
        await asyncio.sleep(0.03)
        return response(exchange[request.url.path])

    with pytest.raises(TimeoutError):
        complete(handle)


def test_rejects_large_content_and_response_envelopes(exchange):
    with pytest.raises(ProposalBudgetExceeded):
        complete(lambda request: response(exchange[request.url.path]), byte_limit=5)
    with pytest.raises(ProposalBudgetExceeded):
        complete(lambda _: response({"prompt": "x" * local_inference.ENVELOPE_BYTES}))


@pytest.mark.parametrize("change", [
    {"truncated": True}, {"stop_type": "limit"}, {"tokens_evaluated": 2},
])
def test_rejects_truncated_generation_and_token_mismatch(exchange, change):
    exchange["/completion"].update(change)
    with pytest.raises(ValueError, match="Incomplete inference response"):
        complete(lambda request: response(exchange[request.url.path]))
