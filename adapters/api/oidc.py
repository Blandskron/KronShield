"""Authenticate against explicitly configured OpenID Connect endpoints."""

import base64
import hmac
from dataclasses import dataclass, field
from hashlib import sha256
from time import time
from urllib.parse import quote_plus, urlencode, urlsplit

import httpx
import jwt

from application.access import AccessError
from application.authentication import Identity, LoginAttempt


def require_https(url: str, *, origin_only: bool = False) -> None:
    parts = urlsplit(url)
    if (
        parts.scheme != "https" or not parts.hostname or parts.username is not None
        or parts.password is not None or parts.fragment or parts.query
        or (origin_only and parts.path)
    ):
        raise ValueError("Expected an HTTPS URL without user info, query or fragment")


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    authorize_url: str
    token_url: str
    jwks_url: str
    introspection_url: str
    client_id: str
    client_secret: str = field(repr=False)
    api_audience: str
    api_scope: str
    web_origin: str

    def __post_init__(self) -> None:
        for url in (self.issuer, self.authorize_url, self.token_url, self.jwks_url, self.introspection_url):
            require_https(url)
        require_https(self.web_origin, origin_only=True)
        if (
            not self.client_id or not self.client_secret or not self.api_audience
            or self.api_audience == self.client_id or len(self.api_scope.split()) != 1
            or self.api_scope.strip() != self.api_scope
        ):
            raise ValueError("Configure a web client, distinct API audience and a single required API scope")

    @property
    def callback(self) -> str:
        return f"{self.web_origin}/api/v1/auth/callback"


def _identity(claims: dict, issuer: str, audience: str) -> Identity:
    subject, audiences = claims.get("sub"), claims.get("aud")
    audiences = [audiences] if isinstance(audiences, str) else audiences
    if (
        claims.get("iss") != issuer
        or not isinstance(subject, str) or not 1 <= len(subject) <= 255
        or not subject.isascii() or not subject.isprintable() or not subject.strip()
        or not isinstance(audiences, list)
        or any(not isinstance(item, str) for item in audiences)
        or audience not in audiences
    ):
        raise AccessError(401, "invalid_identity_claims")
    return Identity(issuer, subject)


class OIDCProvider:
    def __init__(self, settings: OIDCSettings, client: httpx.Client) -> None:
        self.settings = settings
        self.client = client

    def authorization_url(self, state: str, attempt: LoginAttempt) -> str:
        challenge = base64.urlsafe_b64encode(sha256(attempt.verifier.encode("ascii")).digest()).rstrip(b"=")
        query = urlencode({
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.callback,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "nonce": attempt.nonce,
            "code_challenge": challenge.decode("ascii"),
            "code_challenge_method": "S256",
        })
        return f"{self.settings.authorize_url}?{query}"

    def exchange(self, code: str, attempt: LoginAttempt) -> Identity:
        body = self._json("POST", self.settings.token_url, invalid_grant=True, auth=self._credentials, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.callback,
            "code_verifier": attempt.verifier,
        })
        encoded = body.get("id_token")
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 16384:
            raise AccessError(401, "invalid_id_token")
        try:
            header = jwt.get_unverified_header(encoded)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not 1 <= len(kid) <= 256:
                raise ValueError("Missing supported signing key")
            key = self._signing_key(kid)
            claims = jwt.decode(
                encoded, key, algorithms=["RS256"], issuer=self.settings.issuer,
                audience=self.settings.client_id,
                options={"require": ["exp", "iat", "iss", "sub", "aud", "nonce"]},
            )
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
            raise AccessError(401, "invalid_id_token") from None
        nonce = claims["nonce"]
        audiences = claims["aud"]
        if (
            (audiences != self.settings.client_id and audiences != [self.settings.client_id])
            or type(claims["iat"]) is not int or type(claims["exp"]) is not int
            or ("nbf" in claims and type(claims["nbf"]) is not int)
            or not isinstance(nonce, str) or not nonce.isascii() or not hmac.compare_digest(nonce, attempt.nonce)
            or ("azp" in claims and claims["azp"] != self.settings.client_id)
        ):
            raise AccessError(401, "invalid_id_token")
        return _identity(claims, self.settings.issuer, self.settings.client_id)

    def introspect(self, token: str) -> Identity:
        if not 1 <= len(token) <= 8192 or not token.isascii() or not token.isprintable() or " " in token:
            raise AccessError(401, "invalid_token")
        body = self._json("POST", self.settings.introspection_url, auth=self._credentials, data={
            "token": token, "token_type_hint": "access_token",
        })
        expires, not_before = body.get("exp"), body.get("nbf", 0)
        token_type, scope = body.get("token_type", "Bearer"), body.get("scope")
        now = time()
        if (
            body.get("active") is not True or type(expires) is not int or expires <= now
            or type(not_before) is not int or not_before > now
            or not isinstance(token_type, str) or token_type.lower() != "bearer"
            or not isinstance(scope, str) or self.settings.api_scope not in scope.split()
        ):
            raise AccessError(401, "invalid_token")
        return _identity(body, self.settings.issuer, self.settings.api_audience)

    def _signing_key(self, kid: str):
        # Fetch at exchange time so signing-key rotation takes effect without a service restart.
        keys = self._json("GET", self.settings.jwks_url).get("keys")
        if not isinstance(keys, list):
            raise AccessError(503, "identity_provider_unavailable")
        matching = [key for key in keys if isinstance(key, dict) and key.get("kid") == kid
                    and key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
                    and key.get("alg", "RS256") == "RS256"]
        if len(matching) != 1:
            raise ValueError("No unique supported signing key")
        key = jwt.PyJWK.from_dict(matching[0], algorithm="RS256").key
        if key.key_size < 2048:
            raise ValueError("Signing key is too small")
        return key

    @property
    def _credentials(self) -> httpx.BasicAuth:
        # OAuth client_secret_basic encodes both credentials as form components before HTTP Basic.
        return httpx.BasicAuth(quote_plus(self.settings.client_id), quote_plus(self.settings.client_secret))

    def _json(self, method: str, url: str, *, invalid_grant: bool = False, **kwargs) -> dict:
        try:
            response = self.client.request(method, url, follow_redirects=False, **kwargs)
            if invalid_grant and response.status_code == 400:
                payload = response.json()
                if isinstance(payload, dict) and payload.get("error") == "invalid_grant":
                    raise AccessError(401, "invalid_login")
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise AccessError(503, "identity_provider_unavailable") from None
        if not isinstance(body, dict):
            raise AccessError(503, "identity_provider_unavailable")
        return body
