"""Store append-only team selections independently of the project version."""

from alembic import op

revision = "0007_team_selection"
down_revision = "0006_pilot_memberships"
branch_labels = None
depends_on = None

TABLE = "pentest_agent.project_team_selection"
ROLE = "pentest_agent_runtime"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
SCOPE = f"org_id = {ORG} AND project_id = {PROJECT}"
MEMBERSHIP = f"""
    SELECT 1 FROM pentest_agent.project_membership AS m
    WHERE m.org_id = {ORG} AND m.project_id = {PROJECT} AND m.user_id = {ACTOR}
"""


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE {TABLE} (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            version bigint NOT NULL CHECK (version BETWEEN 1 AND 999999999999999999),
            mode_id text NOT NULL CHECK (mode_id ~ '^[a-z][a-z0-9-]{{0,63}}$'),
            mode_version integer NOT NULL CHECK (mode_version > 0),
            mode_digest text NOT NULL CHECK (mode_digest ~ '^[0-9a-f]{{64}}$'),
            actor_id uuid NOT NULL REFERENCES pentest_agent.identity(id),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (org_id, project_id, version),
            FOREIGN KEY (org_id, project_id) REFERENCES pentest_agent.project(org_id, id)
        )
    """)
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {ROLE}")
    op.execute(f"""
        CREATE POLICY member_read ON {TABLE} FOR SELECT TO {ROLE}
        USING ({SCOPE} AND EXISTS ({MEMBERSHIP}))
    """)
    op.execute(f"""
        CREATE POLICY admin_insert ON {TABLE} FOR INSERT TO {ROLE}
        WITH CHECK (
            {SCOPE} AND actor_id = {ACTOR}
            AND EXISTS ({MEMBERSHIP} AND m.role_id = 'project_admin')
            AND EXISTS (
                SELECT 1 FROM pentest_agent.project AS p
                JOIN pentest_agent.organization AS o ON o.id = p.org_id
                WHERE p.org_id = {ORG} AND p.id = {PROJECT}
                AND p.state = 'active' AND o.state = 'active'
            )
        )
    """)


def downgrade() -> None:
    op.drop_table("project_team_selection", schema="pentest_agent")
