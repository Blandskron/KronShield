"""Persist assessments and immutable, offline scope reviews."""

from alembic import op

revision = "0004_scope_review"
down_revision = "0003_engagements"
branch_labels = None
depends_on = None

SCHEMA = "pentest_agent"
ROLE = "pentest_agent_runtime"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
MEMBERSHIP = (
    f"SELECT 1 FROM {SCHEMA}.project_membership AS m "
    f"WHERE m.org_id = {ORG} AND m.project_id = {PROJECT} AND m.user_id = {ACTOR}"
)
TABLES = ("assessment", "assessment_plan", "assessment_plan_target", "assessment_plan_event", "assessment_plan_outbox")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pentest_agent.assessment (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            id uuid NOT NULL,
            actor_id uuid NOT NULL,
            label text NOT NULL CHECK (length(label) BETWEEN 1 AND 160),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, project_id, id),
            FOREIGN KEY (org_id, project_id) REFERENCES pentest_agent.project(org_id, id),
            FOREIGN KEY (org_id, actor_id) REFERENCES pentest_agent.organization_membership(org_id, user_id)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.assessment_plan (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            id uuid NOT NULL,
            actor_id uuid NOT NULL,
            assessment_id uuid NOT NULL,
            authorization_id uuid NOT NULL,
            authorization_revision integer NOT NULL,
            idempotency_digest text NOT NULL CHECK (idempotency_digest ~ '^[0-9a-f]{64}$'),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
            snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
            checked_at timestamptz NOT NULL,
            PRIMARY KEY (org_id, project_id, id),
            UNIQUE (org_id, project_id, actor_id, idempotency_digest),
            FOREIGN KEY (org_id, project_id, assessment_id) REFERENCES pentest_agent.assessment(org_id, project_id, id),
            FOREIGN KEY (org_id, project_id, authorization_id, authorization_revision)
                REFERENCES pentest_agent.authorization(org_id, project_id, id, revision),
            FOREIGN KEY (org_id, actor_id) REFERENCES pentest_agent.organization_membership(org_id, user_id)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.assessment_plan_target (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            plan_id uuid NOT NULL,
            target_id uuid NOT NULL,
            PRIMARY KEY (org_id, project_id, plan_id, target_id),
            FOREIGN KEY (org_id, project_id, plan_id) REFERENCES pentest_agent.assessment_plan(org_id, project_id, id),
            FOREIGN KEY (org_id, project_id, target_id) REFERENCES pentest_agent.target(org_id, project_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.assessment_plan_event (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            plan_id uuid NOT NULL,
            id uuid NOT NULL,
            kind text NOT NULL CHECK (kind = 'scope_review_recorded'),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, project_id, plan_id, id),
            UNIQUE (org_id, project_id, plan_id, kind),
            FOREIGN KEY (org_id, project_id, plan_id) REFERENCES pentest_agent.assessment_plan(org_id, project_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.assessment_plan_outbox (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            plan_id uuid NOT NULL,
            event_id uuid NOT NULL,
            PRIMARY KEY (org_id, project_id, plan_id, event_id),
            FOREIGN KEY (org_id, project_id, plan_id, event_id)
                REFERENCES pentest_agent.assessment_plan_event(org_id, project_id, plan_id, id)
        )
    """)
    for table in TABLES:
        name = f"{SCHEMA}.{table}"
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT INSERT ON {name} TO {ROLE}")
        scoped = f"org_id = {ORG} AND project_id = {PROJECT}"
        if table != "assessment_plan_outbox":
            op.execute(f"GRANT SELECT ON {name} TO {ROLE}")
            op.execute(f"CREATE POLICY member_read ON {name} FOR SELECT TO {ROLE} "
                       f"USING ({scoped} AND EXISTS ({MEMBERSHIP}))")
        owner = f"actor_id = {ACTOR}"
        if table not in {"assessment", "assessment_plan"}:
            owner = (f"EXISTS (SELECT 1 FROM {SCHEMA}.assessment_plan AS p WHERE p.org_id = {ORG} "
                     f"AND p.project_id = {PROJECT} AND p.id = {table}.plan_id AND p.actor_id = {ACTOR})")
        op.execute(f"CREATE POLICY operator_insert ON {name} FOR INSERT TO {ROLE} "
                   f"WITH CHECK ({scoped} AND {owner} AND EXISTS ({MEMBERSHIP} AND m.role_id = 'operator'))")
    op.execute("""
        CREATE INDEX assessment_plan_by_assessment
            ON pentest_agent.assessment_plan(org_id, project_id, assessment_id, id)
    """)
    op.execute("""
        CREATE INDEX assessment_plan_by_authorization
            ON pentest_agent.assessment_plan(org_id, project_id, authorization_id, authorization_revision)
    """)
    op.execute("""
        CREATE INDEX assessment_plan_target_by_target
            ON pentest_agent.assessment_plan_target(org_id, project_id, target_id)
    """)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
