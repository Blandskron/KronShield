"""Allow SARIF projections for the approved requester and reviewer."""

from alembic import op

revision = "0016_sarif_evidence"
down_revision = "0015_event_batch_evidence"
branch_labels = None
depends_on = None

TABLE = "pentest_agent.evidence_projection"
ROLE = "pentest_agent_runtime"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"


def upgrade() -> None:
    membership = f"""SELECT 1 FROM pentest_agent.project_membership AS m
        WHERE (m.org_id, m.project_id, m.user_id) = ({ORG}, {PROJECT}, {ACTOR})"""
    permission = f"""SELECT 1 FROM pentest_agent.evidence_permission AS p
        WHERE (p.org_id, p.project_id, p.id, p.revision) =
          ({ORG}, {PROJECT}, evidence_projection.permission_id, evidence_projection.revision)"""
    decision = f"""SELECT 1 FROM pentest_agent.evidence_decision AS d
        WHERE (d.org_id, d.project_id, d.permission_id, d.revision) =
          ({ORG}, {PROJECT}, evidence_projection.permission_id, evidence_projection.revision)"""
    approved = f"EXISTS ({decision} AND d.kind = 'approve')"
    granted = f"""org_id = {ORG} AND project_id = {PROJECT}
        AND EXISTS ({permission}
          AND p.spec->'sources' @> jsonb_build_array(jsonb_build_object(
              'digest', evidence_projection.source_digest, 'kind', 'sarif-v1', 'capability', 'code-review'))
          AND clock_timestamp() >= (p.spec->>'valid_from')::timestamptz
          AND clock_timestamp() < (p.spec->>'valid_until')::timestamptz
          AND NOT EXISTS (SELECT 1 FROM pentest_agent.evidence_permission AS later
              WHERE (later.org_id, later.project_id, later.id) = (p.org_id, p.project_id, p.id)
                AND later.revision > p.revision))
        AND NOT EXISTS ({decision} AND d.kind = 'revoke')
        AND EXISTS (SELECT 1 FROM pentest_agent.project AS p
            JOIN pentest_agent.organization AS o ON o.id = p.org_id
            WHERE (p.org_id, p.id) = ({ORG}, {PROJECT})
              AND p.state = 'active' AND o.state = 'active' AND NOT o.kill_switch)"""
    owner = f"EXISTS ({membership} AND m.role_id = 'operator') AND EXISTS ({permission} AND p.requester_id = {ACTOR})"
    reviewer = f"""EXISTS ({membership} AND m.role_id = 'approver')
        AND EXISTS ({decision} AND d.kind = 'approve' AND d.actor_id = {ACTOR})"""
    op.execute(f"""
        CREATE POLICY sarif_read ON {TABLE} FOR SELECT TO {ROLE}
        USING ({granted} AND (({owner} AND {approved}) OR ({reviewer})))
    """)
    op.execute(f"""
        CREATE POLICY sarif_insert ON {TABLE} FOR INSERT TO {ROLE}
        WITH CHECK ({granted} AND {owner} AND {approved})
    """)


def downgrade() -> None:
    op.execute(f"DROP POLICY sarif_insert ON {TABLE}")
    op.execute(f"DROP POLICY sarif_read ON {TABLE}")
