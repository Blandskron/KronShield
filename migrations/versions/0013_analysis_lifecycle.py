"""Persist cancellation and private proposal receipts."""

from alembic import op

revision = "0013_analysis_lifecycle"
down_revision = "0012_analysis_step_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE pentest_agent.analysis_step_outcome
            ADD COLUMN strategy text NOT NULL DEFAULT 'deterministic'
                CHECK (strategy IN ('deterministic', 'assisted')),
            ADD COLUMN proposal_error text CHECK (proposal_error ~ '^[a-z0-9_]{1,64}$'),
            ADD COLUMN proposal_receipt jsonb,
            ADD CONSTRAINT valid_analysis_proposal_receipt CHECK (
                proposal_receipt IS NULL AND proposal_error IS NULL
                OR strategy = 'assisted' AND state = 'completed'
                    AND proposal_receipt IS NOT NULL AND jsonb_typeof(proposal_receipt) = 'object'
                    AND proposal_error IS NOT DISTINCT FROM proposal_receipt->>'error'
            )
    """)
    op.execute("""
        GRANT SELECT (strategy, proposal_error) ON pentest_agent.analysis_step_outcome TO pentest_agent_runtime
    """)
    op.execute("""
        CREATE TABLE pentest_agent.analysis_cancellation (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            analysis_id uuid NOT NULL,
            cancelled_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (org_id, project_id, analysis_id),
            FOREIGN KEY (org_id, project_id, analysis_id)
                REFERENCES pentest_agent.offline_analysis(org_id, project_id, id)
        )
    """)
    policy = """
        org_id = NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid
        AND project_id = NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid
        AND EXISTS (
            SELECT 1 FROM pentest_agent.offline_analysis AS a
            WHERE (a.org_id, a.project_id, a.id) =
                  (analysis_cancellation.org_id, analysis_cancellation.project_id, analysis_cancellation.analysis_id)
        )
    """
    op.execute("ALTER TABLE pentest_agent.analysis_cancellation ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pentest_agent.analysis_cancellation FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON pentest_agent.analysis_cancellation TO pentest_agent_runtime")
    op.execute(f"CREATE POLICY owner_read ON pentest_agent.analysis_cancellation FOR SELECT USING ({policy})")
    op.execute(f"CREATE POLICY owner_insert ON pentest_agent.analysis_cancellation FOR INSERT WITH CHECK ({policy})")


def downgrade() -> None:
    op.drop_table("analysis_cancellation", schema="pentest_agent")
    op.execute("""
        ALTER TABLE pentest_agent.analysis_step_outcome
            DROP CONSTRAINT valid_analysis_proposal_receipt,
            DROP COLUMN proposal_receipt, DROP COLUMN proposal_error, DROP COLUMN strategy
    """)
