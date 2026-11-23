"""Persist browser login attempts and sessions with credential-scoped row policies."""

from alembic import op

revision = "0002_authentication"
down_revision = "0001_tenancy"
branch_labels = None
depends_on = None

SCHEMA = "pentest_agent"
ROLE = "pentest_agent_runtime"


def _credential_policies(table: str, expression: str, insert_check: str) -> None:
    name = f"{SCHEMA}.{table}"
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {name} TO {ROLE}")
    op.execute(f"CREATE POLICY credential_read ON {name} FOR SELECT TO {ROLE} USING ({expression})")
    op.execute(f"CREATE POLICY credential_delete ON {name} FOR DELETE TO {ROLE} USING ({expression})")
    op.execute(f"CREATE POLICY credential_insert ON {name} FOR INSERT TO {ROLE} WITH CHECK ({insert_check})")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pentest_agent.login_attempt (
            state_hash text PRIMARY KEY CHECK (state_hash ~ '^[0-9a-f]{64}$'),
            browser_hash text NOT NULL CHECK (browser_hash ~ '^[0-9a-f]{64}$'),
            nonce text NOT NULL,
            verifier text NOT NULL,
            expires_at timestamptz NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.web_session (
            token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            user_id uuid NOT NULL REFERENCES pentest_agent.identity (id) ON DELETE CASCADE,
            csrf text NOT NULL,
            expires_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX login_attempt_expiry ON pentest_agent.login_attempt (expires_at)")
    op.execute("CREATE INDEX web_session_expiry ON pentest_agent.web_session (expires_at)")
    op.execute("CREATE INDEX web_session_user ON pentest_agent.web_session (user_id)")
    op.execute(f"""
        CREATE POLICY verified_identity ON pentest_agent.identity FOR SELECT TO {ROLE}
        USING (issuer = NULLIF(current_setting('pentest_agent.issuer', true), '')
           AND subject = NULLIF(current_setting('pentest_agent.subject', true), ''))
    """)
    attempt = (
        "state_hash = current_setting('pentest_agent.state_hash', true) "
        "AND browser_hash = current_setting('pentest_agent.browser_hash', true)"
    )
    _credential_policies("login_attempt", attempt, attempt)
    session = "token_hash = current_setting('pentest_agent.session_hash', true)"
    _credential_policies("web_session", session,
                         f"{session} AND user_id = NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid")


def downgrade() -> None:
    op.drop_table("web_session", schema=SCHEMA)
    op.drop_table("login_attempt", schema=SCHEMA)
    op.execute("DROP POLICY verified_identity ON pentest_agent.identity")
