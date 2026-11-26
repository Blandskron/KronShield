"""Record immutable offline dispatch outcomes and reasons."""

from alembic import op

revision = "0012_analysis_step_outcomes"
down_revision = "0011_offline_analysis_ledger"
branch_labels = None
depends_on = None

TABLE = "pentest_agent.analysis_step_outcome"
ROLE = "pentest_agent_runtime"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
OWNER = f"""
    org_id = {ORG} AND project_id = {PROJECT}
    AND EXISTS (
        SELECT 1 FROM pentest_agent.offline_analysis AS a
        WHERE (a.org_id, a.project_id, a.id) =
          (analysis_step_outcome.org_id, analysis_step_outcome.project_id, analysis_step_outcome.analysis_id)
    )
"""


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE {TABLE} (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            analysis_id uuid NOT NULL,
            idempotency_digest text NOT NULL CHECK (idempotency_digest ~ '^[a-f0-9]{{64}}$'),
            step_id text NOT NULL CHECK (length(step_id) BETWEEN 1 AND 64),
            reservation_id uuid,
            state text NOT NULL CHECK (state IN ('completed', 'blocked', 'failed')),
            reason text CHECK (reason ~ '^[a-z0-9_]{{1,64}}$'),
            output jsonb,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK (
                (state = 'completed' AND reservation_id IS NOT NULL AND output IS NOT NULL
                 AND jsonb_typeof(output) = 'object' AND reason IS NULL)
                OR (state IN ('blocked', 'failed') AND output IS NULL AND reason IS NOT NULL)
            ),
            PRIMARY KEY (org_id, project_id, analysis_id, idempotency_digest),
            FOREIGN KEY (org_id, project_id, analysis_id)
                REFERENCES pentest_agent.offline_analysis(org_id, project_id, id),
            FOREIGN KEY (org_id, project_id, analysis_id, reservation_id)
                REFERENCES pentest_agent.analysis_reservation(org_id, project_id, analysis_id, id)
        )
    """)
    op.execute(f"""
        CREATE UNIQUE INDEX completed_analysis_step ON {TABLE} (org_id, project_id, analysis_id, step_id)
        WHERE state = 'completed'
    """)
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    # Stored outcomes are readable as receipts. The output column is reserved for a future authorized review flow.
    op.execute(f"""
        GRANT SELECT (org_id, project_id, analysis_id, idempotency_digest, step_id, reservation_id,
                      state, reason, created_at), INSERT ON {TABLE} TO {ROLE}
    """)
    op.execute(f"CREATE POLICY owner_read ON {TABLE} FOR SELECT TO {ROLE} USING ({OWNER})")
    op.execute(f"CREATE POLICY owner_insert ON {TABLE} FOR INSERT TO {ROLE} WITH CHECK ({OWNER})")


def downgrade() -> None:
    op.drop_table("analysis_step_outcome", schema="pentest_agent")
