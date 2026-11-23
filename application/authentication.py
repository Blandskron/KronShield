"""Login credentials and opaque browser sessions shared by the HTTP adapters."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID

from application.access import AccessError


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str


@dataclass(frozen=True)
class LoginAttempt:
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class WebSession:
    user_id: UUID
    csrf: str = field(repr=False)
    expires_at: datetime


class IdentityProvider(Protocol):
    def authorization_url(self, state: str, attempt: LoginAttempt) -> str: ...
    def exchange(self, code: str, attempt: LoginAttempt) -> Identity: ...
    def introspect(self, token: str) -> Identity: ...


class AuthStore(Protocol):
    def save_attempt(self, state_hash: str, browser_hash: str, attempt: LoginAttempt) -> None: ...
    def consume_attempt(self, state_hash: str, browser_hash: str) -> LoginAttempt | None: ...
    def identity_id(self, identity: Identity) -> UUID | None: ...
    def replace_session(self, session_hash: str, session: WebSession, previous_hash: str | None) -> None: ...
    def session(self, session_hash: str) -> WebSession | None: ...
    def revoke_session(self, session_hash: str) -> None: ...


def credential_hash(value: str | None) -> str | None:
    # Opaque browser values are always unpadded base64url with 32 random bytes.
    if value is None or len(value) != 43 or not value.isascii() or not (
        value.replace("-", "a").replace("_", "a").isalnum()
    ):
        return None
    return sha256(value.encode("ascii")).hexdigest()


class Authentication:
    login_ttl = timedelta(minutes=5)
    session_ttl = timedelta(hours=8)

    def __init__(self, provider: IdentityProvider, store: AuthStore) -> None:
        self.provider = provider
        self.store = store

    def start_login(self) -> tuple[str, str]:
        state, browser = token_urlsafe(32), token_urlsafe(32)
        attempt = LoginAttempt(token_urlsafe(32), token_urlsafe(32),
                               datetime.now(timezone.utc) + self.login_ttl)
        self.store.save_attempt(sha256(state.encode()).hexdigest(), sha256(browser.encode()).hexdigest(), attempt)
        return self.provider.authorization_url(state, attempt), browser

    def finish_login(self, state: str, code: str, browser: str | None, previous_session: str | None) -> str:
        state_hash, browser_hash = credential_hash(state), credential_hash(browser)
        if not state_hash or not browser_hash or not code or len(code) > 4096:
            raise AccessError(401, "invalid_login")
        attempt = self.store.consume_attempt(state_hash, browser_hash)
        if attempt is None:
            raise AccessError(401, "invalid_login")
        user_id = self._user_id(self.provider.exchange(code, attempt))
        return self.issue_session(user_id, previous_session)

    def issue_session(self, user_id: UUID, previous_session: str | None) -> str:
        token = token_urlsafe(32)
        session = WebSession(user_id, token_urlsafe(32), datetime.now(timezone.utc) + self.session_ttl)
        self.store.replace_session(sha256(token.encode()).hexdigest(), session, credential_hash(previous_session))
        return token

    def browser_session(self, token: str) -> WebSession:
        digest = credential_hash(token)
        session = self.store.session(digest) if digest else None
        if session is None:
            raise AccessError(401, "invalid_session")
        return session

    def bearer_user(self, token: str) -> UUID:
        return self._user_id(self.provider.introspect(token))

    def logout(self, token: str) -> None:
        digest = credential_hash(token)
        if digest:
            self.store.revoke_session(digest)

    def _user_id(self, identity: Identity) -> UUID:
        user_id = self.store.identity_id(identity)
        if user_id is None:
            raise AccessError(401, "unknown_identity")
        return user_id
