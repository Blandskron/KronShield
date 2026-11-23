"""Record immutable project imports and expose only the Alembic revision for readiness."""

from alembic import op

revision = "0005_legacy_import"
down_revision = "0004_scope_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pentest_agent.legacy_import (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            id uuid NOT NULL,
            actor_id uuid NOT NULL,
            source_format text NOT NULL CHECK (source_format IN ('json', 'sqlite')),
            source_digest text NOT NULL CHECK (source_digest ~ '^[0-9a-f]{64}$'),
            findings jsonb NOT NULL CHECK (jsonb_typeof(findings) = 'array' AND jsonb_array_length(findings) <= 1000),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, project_id, id),
            UNIQUE (org_id, project_id, source_digest),
            FOREIGN KEY (org_id, project_id) REFERENCES pentest_agent.project(org_id, id),
            FOREIGN KEY (org_id, actor_id) REFERENCES pentest_agent.organization_membership(org_id, user_id)
        )
    """)
    op.execute("ALTER TABLE pentest_agent.legacy_import ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pentest_agent.legacy_import FORCE ROW LEVEL SECURITY")
    op.execute("GRANT INSERT, SELECT ON pentest_agent.legacy_import TO pentest_agent_runtime")
    op.execute("GRANT SELECT ON public.pentest_agent_alembic_version TO pentest_agent_runtime")
    scope = """
        org_id = NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid
        AND project_id = NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid
    """
    lookup = """
        SELECT 1 FROM pentest_agent.project_membership AS m
        WHERE m.org_id = legacy_import.org_id AND m.project_id = legacy_import.project_id
        AND m.user_id = NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid
    """
    op.execute(f"""
        CREATE POLICY member_read ON pentest_agent.legacy_import FOR SELECT TO pentest_agent_runtime
        USING ({scope} AND EXISTS ({lookup}))
    """)
    op.execute(f"""
        CREATE POLICY operator_insert ON pentest_agent.legacy_import FOR INSERT TO pentest_agent_runtime
        WITH CHECK ({scope} AND EXISTS ({lookup} AND m.role_id = 'operator')
                    AND actor_id = NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public.pentest_agent_alembic_version FROM pentest_agent_runtime")
    op.drop_table("legacy_import", schema="pentest_agent")
