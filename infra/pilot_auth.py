"""Store pilot-only credentials with distinct browser and CLI token types."""

from hashlib import scrypt
from hmac import compare_digest
from os import urandom
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import text

from application.access import AccessError
from application.authentication import Identity, credential_hash
from infra.auth_store import _set_local

PILOT_ISSUER = "urn:pentest-agent:pilot"
TOKEN_SECONDS = 3600


def _password_hash(password: str, salt: bytes) -> bytes:
    return scrypt(password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)


class PilotStore:
    def __init__(self, engine, bootstrap_secret: str) -> None:
        self.engine = engine
        self.bootstrap_secret = bootstrap_secret

    def enroll(self, username: str, password: str, *, actor=None, bootstrap_code: str | None = None):
        if bootstrap_code is not None and not compare_digest(bootstrap_code.encode(), self.bootstrap_secret.encode()):
            raise AccessError(401, "invalid_bootstrap_code")
        user_id, salt = uuid4(), urandom(16)
        with self.engine.begin() as connection:
            if bootstrap_code is not None:
                _set_local(connection, "pilot_bootstrap", "on")
                claimed = connection.scalar(text("""
                    INSERT INTO pentest_agent.pilot_bootstrap (redeemed) VALUES (true)
                    ON CONFLICT DO NOTHING RETURNING redeemed
                """))
                if not claimed:
                    raise AccessError(409, "bootstrap_already_redeemed")
            else:
                _set_local(connection, "user_id", str(actor))
                if not connection.scalar(text("SELECT true FROM pentest_agent.platform_admin WHERE user_id = :id"),
                                         {"id": actor}):
                    raise AccessError(403, "permission_denied")
            _set_local(connection, "pilot_enroll", str(user_id))
            args = {"id": user_id, "username": username, "issuer": PILOT_ISSUER,
                    "salt": salt, "digest": _password_hash(password, salt)}
            connection.execute(text("""
                INSERT INTO pentest_agent.identity (id, issuer, subject) VALUES (:id, :issuer, :username)
            """), args)
            connection.execute(text("""
                INSERT INTO pentest_agent.pilot_account (user_id, username, salt, password_hash)
                VALUES (:id, :username, :salt, :digest)
            """), args)
            if bootstrap_code is not None:
                connection.execute(text("INSERT INTO pentest_agent.platform_admin (user_id) VALUES (:id)"), args)
        return user_id

    def authenticate(self, username: str, password: str):
        with self.engine.begin() as connection:
            _set_local(connection, "pilot_username", username)
            row = connection.execute(text("""
                SELECT user_id, salt, password_hash FROM pentest_agent.pilot_account WHERE username = :user
            """), {"user": username}).one_or_none()
        derived = _password_hash(password, row.salt if row else bytes(16))
        if row is None or not compare_digest(derived, row.password_hash):
            raise AccessError(401, "invalid_credentials")
        return row.user_id

    def issue_token(self, user_id, username: str) -> str:
        token = token_urlsafe(32)
        digest = credential_hash(token)
        with self.engine.begin() as connection:
            _set_local(connection, "pilot_digest", digest)
            _set_local(connection, "user_id", str(user_id))
            connection.execute(text("""
                INSERT INTO pentest_agent.pilot_token (digest, user_id, username, expires_at)
                VALUES (:digest, :user, :username, now() + make_interval(secs => :ttl))
            """), {"digest": digest, "user": user_id, "username": username, "ttl": TOKEN_SECONDS})
        return token

    def revoke_token(self, token: str) -> None:
        digest = credential_hash(token)
        if not digest:
            raise AccessError(401, "invalid_token")
        with self.engine.begin() as connection:
            _set_local(connection, "pilot_digest", digest)
            connection.execute(text("DELETE FROM pentest_agent.pilot_token WHERE digest = :digest"), {"digest": digest})

    def introspect(self, token: str) -> Identity:
        digest = credential_hash(token)
        if not digest:
            raise AccessError(401, "invalid_token")
        with self.engine.begin() as connection:
            _set_local(connection, "pilot_digest", digest)
            username = connection.scalar(text("""
                SELECT username FROM pentest_agent.pilot_token WHERE digest = :digest AND expires_at > now()
            """), {"digest": digest})
        if not username:
            raise AccessError(401, "invalid_token")
        return Identity(PILOT_ISSUER, username)

    def authorization_url(self, state, attempt):
        raise AccessError(404, "oidc_unavailable")

    def exchange(self, code, attempt):
        raise AccessError(404, "oidc_unavailable")
