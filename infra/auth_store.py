"""Store and authorize HTTP identities through the PostgreSQL runtime role."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from application.access import AccessError, Action, ProjectAccess, authorize_project
from application.authentication import Identity, LoginAttempt, WebSession
from infra.tenancy import tenant_transaction


def _set_local(connection: Connection, name: str, value: str) -> None:
    connection.execute(text("SELECT set_config(:name, :value, true)"), {"name": f"pentest_agent.{name}", "value": value})


RUNTIME_ROLE_QUERY = """
                SELECT NOT (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication)
                    AND pg_has_role(current_user, 'pentest_agent_runtime', 'USAGE')
                    AND NOT EXISTS (
                        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'pentest_agent' AND c.relkind IN ('r', 'p')
                          AND pg_has_role(r.oid, c.relowner, 'MEMBER')
                    )
                FROM pg_roles r WHERE r.rolname = current_user
"""


class UnsafeRuntimeRole(RuntimeError):
    pass


class PostgresAuthStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def verify_runtime_role(self) -> None:
        with self.engine.connect() as connection:
            allowed = connection.scalar(text(RUNTIME_ROLE_QUERY))
        if not allowed:
            raise UnsafeRuntimeRole("Use a non-owner database login granted pentest_agent_runtime")

    def save_attempt(self, state_hash: str, browser_hash: str, attempt: LoginAttempt) -> None:
        with self.engine.begin() as connection:
            _set_local(connection, "state_hash", state_hash)
            _set_local(connection, "browser_hash", browser_hash)
            connection.execute(text("""
                INSERT INTO pentest_agent.login_attempt (state_hash, browser_hash, nonce, verifier, expires_at)
                VALUES (:state, :browser, :nonce, :verifier, :expires)
            """), {"state": state_hash, "browser": browser_hash, "nonce": attempt.nonce,
                   "verifier": attempt.verifier, "expires": attempt.expires_at})

    def consume_attempt(self, state_hash: str, browser_hash: str) -> LoginAttempt | None:
        with self.engine.begin() as connection:
            _set_local(connection, "state_hash", state_hash)
            _set_local(connection, "browser_hash", browser_hash)
            row = connection.execute(text("""
                DELETE FROM pentest_agent.login_attempt
                WHERE state_hash = :state AND browser_hash = :browser AND expires_at > now()
                RETURNING nonce, verifier, expires_at
            """), {"state": state_hash, "browser": browser_hash}).one_or_none()
            return LoginAttempt(*row) if row else None

    def identity_id(self, identity: Identity) -> UUID | None:
        with self.engine.begin() as connection:
            _set_local(connection, "issuer", identity.issuer)
            _set_local(connection, "subject", identity.subject)
            return connection.scalar(text("""
                SELECT id FROM pentest_agent.identity WHERE issuer = :issuer AND subject = :subject
            """), {"issuer": identity.issuer, "subject": identity.subject})

    def replace_session(self, session_hash: str, session: WebSession, previous_hash: str | None) -> None:
        with self.engine.begin() as connection:
            if previous_hash:
                self._delete_session(connection, previous_hash)
            _set_local(connection, "session_hash", session_hash)
            _set_local(connection, "user_id", str(session.user_id))
            connection.execute(text("""
                INSERT INTO pentest_agent.web_session (token_hash, user_id, csrf, expires_at)
                VALUES (:token, :user, :csrf, :expires)
            """), {"token": session_hash, "user": session.user_id,
                   "csrf": session.csrf, "expires": session.expires_at})

    def session(self, session_hash: str) -> WebSession | None:
        with self.engine.begin() as connection:
            _set_local(connection, "session_hash", session_hash)
            row = connection.execute(text("""
                SELECT user_id, csrf, expires_at FROM pentest_agent.web_session
                WHERE token_hash = :token AND expires_at > now()
            """), {"token": session_hash}).one_or_none()
            return WebSession(*row) if row else None

    def revoke_session(self, session_hash: str) -> None:
        with self.engine.begin() as connection:
            self._delete_session(connection, session_hash)

    @staticmethod
    def _delete_session(connection: Connection, session_hash: str) -> None:
        _set_local(connection, "session_hash", session_hash)
        connection.execute(text("DELETE FROM pentest_agent.web_session WHERE token_hash = :token"),
                           {"token": session_hash})

    def check_project(self, user_id: UUID, org_id: UUID, project_id: UUID, action: Action) -> None:
        with self.project(user_id, org_id, project_id, action):
            pass

    @contextmanager
    def project(
        self, user_id: UUID, org_id: UUID, project_id: UUID, action: Action, *, guard_membership: bool = False,
    ) -> Iterator[tuple[Connection, ProjectAccess]]:
        with tenant_transaction(self.engine, user_id=user_id, org_id=org_id, project_id=project_id) as connection:
            if guard_membership:
                connection.execute(text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:key, 0))"),
                                   {"key": f"analysis-membership/{org_id}/{user_id}"})
            row = connection.execute(text("""
                SELECT om.role_id, pm.role_id, p.state
                FROM pentest_agent.project AS p
                JOIN pentest_agent.organization AS o ON o.id = p.org_id
                JOIN pentest_agent.organization_membership AS om ON om.org_id = o.id AND om.user_id = :user
                JOIN pentest_agent.project_membership AS pm
                  ON pm.org_id = p.org_id AND pm.project_id = p.id AND pm.user_id = :user
                WHERE p.org_id = :org AND p.id = :project AND o.state = 'active'
            """), {"org": org_id, "project": project_id, "user": user_id}).one_or_none()
            membership = (row[0], row[1]) if row else None
            decision = authorize_project(org_id, project_id, user_id, membership, action)
            if row[2] == "archived" and action in {Action.MANAGE_TARGETS, Action.REQUEST_AUTHORIZATION}:
                raise AccessError(409, "project_archived")
            yield connection, decision
