"""Admit encrypted projections for authorized event batches."""

from alembic import op

revision = "0015_event_batch_evidence"
down_revision = "0014_analysis_publication"
branch_labels = None
depends_on = None

TABLE = "pentest_agent.evidence_projection"
ROLE = "pentest_agent_runtime"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
SCOPE = f"org_id = {ORG} AND project_id = {PROJECT}"


def _update_policies(*, event_batches: bool) -> None:
    membership = f"""SELECT 1 FROM pentest_agent.project_membership AS m
                     WHERE m.org_id = {ORG} AND m.project_id = {PROJECT} AND m.user_id = {ACTOR}"""
    parent = f"""SELECT 1 FROM pentest_agent.evidence_permission AS p
                 WHERE p.org_id = {ORG} AND p.project_id = {PROJECT}
                   AND p.id = evidence_projection.permission_id AND p.revision = evidence_projection.revision"""
    decision = f"""SELECT 1 FROM pentest_agent.evidence_decision AS d
                   WHERE d.org_id = {ORG} AND d.project_id = {PROJECT}
                     AND d.permission_id = evidence_projection.permission_id
                     AND d.revision = evidence_projection.revision"""
    control = """p.spec->'sources' @> jsonb_build_array(jsonb_build_object(
        'digest', evidence_projection.source_digest, 'kind', 'control-observations-v1'))"""
    event_batch = """p.spec->'sources' @> jsonb_build_array(jsonb_build_object(
        'digest', evidence_projection.source_digest, 'kind', 'event-batch-v1', 'capability', 'event-review'))"""
    source_match = f"({control} OR {event_batch})" if event_batches else control
    granted = f"""EXISTS ({parent}
        AND {source_match}
        AND clock_timestamp() >= (p.spec->>'valid_from')::timestamptz
        AND clock_timestamp() < (p.spec->>'valid_until')::timestamptz
        AND NOT EXISTS (SELECT 1 FROM pentest_agent.evidence_permission AS later
            WHERE later.org_id = {ORG} AND later.project_id = {PROJECT}
              AND later.id = p.id AND later.revision > p.revision)
    ) AND NOT EXISTS ({decision} AND d.kind = 'revoke')"""
    active = f"""EXISTS (SELECT 1 FROM pentest_agent.project AS p
        JOIN pentest_agent.organization AS o ON o.id = p.org_id
        WHERE p.org_id = {ORG} AND p.id = {PROJECT}
          AND p.state = 'active' AND o.state = 'active' AND NOT o.kill_switch)"""
    owner = f"EXISTS ({membership} AND m.role_id = 'operator') AND EXISTS ({parent} AND p.requester_id = {ACTOR})"
    approver = f"""EXISTS ({membership} AND m.role_id = 'approver')
        AND EXISTS ({decision} AND d.kind = 'approve' AND d.actor_id = {ACTOR})"""
    op.execute(f"""
        ALTER POLICY member_read ON {TABLE} TO {ROLE}
        USING ({SCOPE} AND (({owner}) OR ({approver})) AND {granted} AND {active})
    """)
    op.execute(f"""
        ALTER POLICY member_insert ON {TABLE} TO {ROLE}
        WITH CHECK ({SCOPE} AND {owner} AND {granted} AND {active} AND EXISTS ({decision} AND d.kind = 'approve'))
    """)


def upgrade() -> None:
    _update_policies(event_batches=True)


def downgrade() -> None:
    _update_policies(event_batches=False)
