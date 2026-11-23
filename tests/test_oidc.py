import base64
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from time import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from adapters.api.oidc import OIDCProvider, OIDCSettings
from application.access import AccessError
from application.authentication import Identity, LoginAttempt


@pytest.fixture(scope="module")
def key_pair():
    return [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)]


@pytest.fixture
def oidc(key_pair):
    settings = OIDCSettings(
        issuer="https://identity.example",
        authorize_url="https://identity.example/auth",
        token_url="https://identity.example/token",
        jwks_url="https://identity.example/keys",
        introspection_url="https://identity.example/introspect",
        client_id="web-client",
        client_secret="x:y",
        api_audience="pentest-api",
        api_scope="pentest:api",
        web_origin="https://app.example",
    )
    keys = [json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())) for key in key_pair]
    for index, key in enumerate(keys):
        key["kid"] = str(index)
    attempt = LoginAttempt("nonce-value", "v" * 43, datetime.now(timezone.utc) + timedelta(minutes=5))
    claims = {"iss": settings.issuer, "aud": settings.client_id, "sub": "alice", "nonce": attempt.nonce,
              "iat": int(time()) - 1, "exp": int(time()) + 60}
    bearer = {"iss": settings.issuer, "aud": [settings.api_audience], "sub": "alice", "active": True,
              "scope": "openid pentest:api", "exp": int(time()) + 60, "token_type": "Bearer"}
    data = {"claims": claims, "bearer": bearer, "key": 0}

    def handle(request):
        if request.url.path == "/token":
            form = parse_qs(request.content.decode())
            assert form["code_verifier"] == [attempt.verifier]
            assert form["redirect_uri"] == [settings.callback]
            assert form["grant_type"] == ["authorization_code"]
            assert base64.b64decode(request.headers["authorization"].split()[1]) == b"web-client:x%3Ay"
            index = data["key"]
            encoded = jwt.encode(data["claims"], key_pair[index], algorithm="RS256", headers={"kid": str(index)})
            return httpx.Response(200, json={"id_token": encoded})
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [keys[data["key"]]]})
        if request.url.path == "/introspect":
            assert parse_qs(request.content.decode()) == {"token": ["example-token"],
                                                           "token_type_hint": ["access_token"]}
            if data.get("outage"):
                return httpx.Response(503)
            return httpx.Response(200, json=data["bearer"])
        raise AssertionError(request.url.path)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        yield OIDCProvider(settings, client), attempt, data


def test_authorization_code_pkce_and_rotated_signing_key(oidc):
    provider, attempt, data = oidc
    query = parse_qs(urlsplit(provider.authorization_url("expected-state", attempt)).query)
    challenge = base64.urlsafe_b64encode(sha256(attempt.verifier.encode()).digest()).rstrip(b"=")
    assert query["code_challenge"] == [challenge.decode()]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["expected-state"]
    assert query["nonce"] == [attempt.nonce]
    for key in [0, 1]:
        data["key"] = key
        assert provider.exchange("example-code", attempt) == Identity(provider.settings.issuer, "alice")


@pytest.mark.parametrize(("field", "value"), [
    ("iss", "https://other.example"), ("aud", "another-client"), ("sub", ""),
    ("exp", 1), ("iat", 2**45), ("exp", True), ("nonce", "other"),
    ("nonce", "caf\u00e9"), ("aud", ["web-client", "other"]), ("azp", "other"),
])
def test_web_exchange_rejects_invalid_claims(oidc, field, value):
    provider, attempt, data = oidc
    data["claims"][field] = value
    with pytest.raises(AccessError) as rejected:
        provider.exchange("example-code", attempt)
    assert rejected.value.status == 401


@pytest.mark.parametrize(("field", "value"), [
    ("active", False), ("active", 1), ("exp", 0), ("exp", True), ("nbf", 2**45),
    ("iss", "https://other.example"), ("aud", "web-client"), ("scope", "openid"),
    ("sub", ""), ("token_type", "refresh_token"),
])
def test_cli_token_is_revalidated_and_denied_when_inactive_or_invalid(oidc, field, value):
    provider, _, data = oidc
    assert provider.introspect("example-token").subject == "alice"
    data["bearer"][field] = value
    with pytest.raises(AccessError) as rejected:
        provider.introspect("example-token")
    assert rejected.value.status == 401


def test_provider_outage_fails_closed(oidc):
    provider, _, data = oidc
    data["outage"] = True
    with pytest.raises(AccessError) as rejected:
        provider.introspect("example-token")
    assert rejected.value.status == 503
