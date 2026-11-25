"""Persist evidence permission revisions, decisions and encrypted projections."""

from alembic import op

revision = "0008_evidence_permissions"
down_revision = "0007_team_selection"
branch_labels = None
depends_on = None

SCHEMA = "pentest_agent"
ROLE = "pentest_agent_runtime"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
SCOPE = f"org_id = {ORG} AND project_id = {PROJECT}"
MEMBER = f"""SELECT 1 FROM {SCHEMA}.project_membership AS m
             WHERE m.org_id = {ORG} AND m.project_id = {PROJECT} AND m.user_id = {ACTOR}"""
OPERATOR = f"EXISTS ({MEMBER} AND m.role_id = 'operator')"
APPROVER = f"EXISTS ({MEMBER} AND m.role_id = 'approver')"
ACTIVE = f"""EXISTS (SELECT 1 FROM {SCHEMA}.project AS p
              JOIN {SCHEMA}.organization AS o ON o.id = p.org_id
              WHERE p.org_id = {ORG} AND p.id = {PROJECT}
              AND p.state = 'active' AND o.state = 'active' AND NOT o.kill_switch)"""


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pentest_agent.evidence_permission (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            id uuid NOT NULL,
            revision integer NOT NULL CHECK (revision > 0),
            requester_id uuid NOT NULL REFERENCES pentest_agent.identity(id),
            plan_id uuid NOT NULL,
            idempotency_digest text NOT NULL CHECK (idempotency_digest ~ '^[0-9a-f]{64}$'),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            spec jsonb NOT NULL CHECK (jsonb_typeof(spec) = 'object'),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (org_id, project_id, id, revision),
            UNIQUE (org_id, project_id, requester_id, idempotency_digest),
            FOREIGN KEY (org_id, project_id, plan_id)
                REFERENCES pentest_agent.assessment_plan(org_id, project_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.evidence_decision (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            permission_id uuid NOT NULL,
            revision integer NOT NULL,
            kind text NOT NULL CHECK (kind IN ('approve', 'revoke')),
            actor_id uuid NOT NULL REFERENCES pentest_agent.identity(id),
            reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (org_id, project_id, permission_id, revision, kind),
            FOREIGN KEY (org_id, project_id, permission_id, revision)
                REFERENCES pentest_agent.evidence_permission(org_id, project_id, id, revision)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.evidence_projection (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            id uuid NOT NULL,
            permission_id uuid NOT NULL,
            revision integer NOT NULL,
            source_digest text NOT NULL CHECK (source_digest ~ '^[0-9a-f]{64}$'),
            projection_digest text NOT NULL CHECK (projection_digest ~ '^[0-9a-f]{64}$'),
            nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
            ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 17 AND 1048592),
            PRIMARY KEY (org_id, project_id, id),
            UNIQUE (org_id, project_id, permission_id, revision, source_digest),
            FOREIGN KEY (org_id, project_id, permission_id, revision)
                REFERENCES pentest_agent.evidence_permission(org_id, project_id, id, revision)
        )
    """)
    for name in ("evidence_permission", "evidence_decision", "evidence_projection"):
        table = f"{SCHEMA}.{name}"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {ROLE}")

    op.execute(f"""
        CREATE POLICY member_read ON {SCHEMA}.evidence_permission FOR SELECT TO {ROLE}
        USING ({SCOPE} AND EXISTS ({MEMBER}) AND (requester_id = {ACTOR} OR {APPROVER}))
    """)
    op.execute(f"""
        CREATE POLICY requester_insert ON {SCHEMA}.evidence_permission FOR INSERT TO {ROLE}
        WITH CHECK ({SCOPE} AND requester_id = {ACTOR} AND {OPERATOR} AND {ACTIVE})
    """)
    for name in ("evidence_decision", "evidence_projection"):
        parent = f"""SELECT 1 FROM {SCHEMA}.evidence_permission AS p
                     WHERE p.org_id = {ORG} AND p.project_id = {PROJECT}
                       AND p.id = {name}.permission_id AND p.revision = {name}.revision"""
        if name == "evidence_decision":
            read = f"EXISTS ({parent})"
            write = f"{APPROVER} AND actor_id = {ACTOR} AND EXISTS ({parent} AND p.requester_id <> {ACTOR})"
        else:
            decision = f"""SELECT 1 FROM {SCHEMA}.evidence_decision AS d
                           WHERE d.org_id = {ORG} AND d.project_id = {PROJECT}
                           AND d.permission_id = {name}.permission_id AND d.revision = {name}.revision"""
            granted = f"""EXISTS ({parent}
                AND p.spec->'sources' @> jsonb_build_array(jsonb_build_object(
                    'digest', {name}.source_digest, 'kind', 'control-observations-v1'))
                AND clock_timestamp() >= (p.spec->>'valid_from')::timestamptz
                AND clock_timestamp() < (p.spec->>'valid_until')::timestamptz
                AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.evidence_permission AS later
                    WHERE later.org_id = {ORG} AND later.project_id = {PROJECT}
                    AND later.id = p.id AND later.revision > p.revision)
            ) AND NOT EXISTS ({decision} AND d.kind = 'revoke')"""
            owner = f"{OPERATOR} AND EXISTS ({parent} AND p.requester_id = {ACTOR})"
            approving_actor = f"{APPROVER} AND EXISTS ({decision} AND d.kind = 'approve' AND d.actor_id = {ACTOR})"
            read = f"(({owner}) OR ({approving_actor})) AND {granted} AND {ACTIVE}"
            write = f"{owner} AND {granted} AND {ACTIVE} AND EXISTS ({decision} AND d.kind = 'approve')"
        op.execute(f"CREATE POLICY member_read ON {SCHEMA}.{name} FOR SELECT TO {ROLE} USING ({SCOPE} AND {read})")
        op.execute(f"CREATE POLICY member_insert ON {SCHEMA}.{name} FOR INSERT TO {ROLE} WITH CHECK ({SCOPE} AND {write})")


def downgrade() -> None:
    for name in ("evidence_projection", "evidence_decision", "evidence_permission"):
        op.drop_table(name, schema=SCHEMA)
