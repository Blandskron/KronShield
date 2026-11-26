"""Persist offline analysis snapshots, events and metered step reservations."""

from alembic import op

revision = "0011_offline_analysis_ledger"
down_revision = "0010_organization_stop"
branch_labels = None
depends_on = None

SCHEMA = "pentest_agent"
ROLE = "pentest_agent_runtime"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
SCOPE = f"org_id = {ORG} AND project_id = {PROJECT}"
OPERATOR = f"""EXISTS (SELECT 1 FROM {SCHEMA}.project_membership AS m
                        WHERE m.org_id = {ORG} AND m.project_id = {PROJECT}
                          AND m.user_id = {ACTOR} AND m.role_id = 'operator')"""
TABLES = ("offline_analysis", "analysis_reservation", "analysis_settlement", "analysis_event")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pentest_agent.offline_analysis (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            id uuid NOT NULL,
            actor_id uuid NOT NULL REFERENCES pentest_agent.identity(id),
            plan_id uuid NOT NULL,
            permission_id uuid NOT NULL,
            permission_revision integer NOT NULL,
            selection_version bigint NOT NULL,
            idempotency_digest text NOT NULL CHECK (idempotency_digest ~ '^[a-f0-9]{64}$'),
            request_digest text NOT NULL CHECK (request_digest ~ '^[a-f0-9]{64}$'),
            snapshot_digest text NOT NULL CHECK (snapshot_digest ~ '^[a-f0-9]{64}$'),
            snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (org_id, project_id, id),
            UNIQUE (org_id, project_id, actor_id, idempotency_digest),
            FOREIGN KEY (org_id, project_id, plan_id)
                REFERENCES pentest_agent.assessment_plan(org_id, project_id, id),
            FOREIGN KEY (org_id, project_id, selection_version)
                REFERENCES pentest_agent.project_team_selection(org_id, project_id, version),
            FOREIGN KEY (org_id, project_id, permission_id, permission_revision)
                REFERENCES pentest_agent.evidence_permission(org_id, project_id, id, revision)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.analysis_reservation (
            org_id uuid NOT NULL, project_id uuid NOT NULL, analysis_id uuid NOT NULL,
            id uuid NOT NULL,
            idempotency_digest text NOT NULL CHECK (idempotency_digest ~ '^[a-f0-9]{64}$'),
            request_digest text NOT NULL CHECK (request_digest ~ '^[a-f0-9]{64}$'),
            step_id text NOT NULL CHECK (length(step_id) BETWEEN 1 AND 64),
            input_bytes integer NOT NULL CHECK (input_bytes >= 0),
            calls integer NOT NULL CHECK (calls BETWEEN 0 AND 6),
            input_tokens integer NOT NULL CHECK (input_tokens >= 0),
            output_tokens integer NOT NULL CHECK (output_tokens >= 0),
            CHECK (calls > 0 OR (input_tokens = 0 AND output_tokens = 0)),
            started_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL CHECK (expires_at > started_at),
            PRIMARY KEY (org_id, project_id, analysis_id, id),
            UNIQUE (org_id, project_id, analysis_id, idempotency_digest),
            FOREIGN KEY (org_id, project_id, analysis_id)
                REFERENCES pentest_agent.offline_analysis(org_id, project_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.analysis_settlement (
            org_id uuid NOT NULL, project_id uuid NOT NULL, analysis_id uuid NOT NULL, id uuid NOT NULL,
            outcome text NOT NULL CHECK (outcome IN ('measured', 'unknown', 'timeout')),
            input_bytes integer NOT NULL CHECK (input_bytes >= 0),
            calls integer NOT NULL CHECK (calls >= 0),
            input_tokens integer NOT NULL CHECK (input_tokens >= 0),
            output_tokens integer NOT NULL CHECK (output_tokens >= 0),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (org_id, project_id, analysis_id, id),
            FOREIGN KEY (org_id, project_id, analysis_id, id)
                REFERENCES pentest_agent.analysis_reservation(org_id, project_id, analysis_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.analysis_event (
            org_id uuid NOT NULL, project_id uuid NOT NULL, analysis_id uuid NOT NULL,
            sequence bigint NOT NULL CHECK (sequence > 0),
            kind text NOT NULL CHECK (kind IN ('draft_recorded', 'step_reserved', 'step_settled')),
            reservation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK ((kind = 'draft_recorded') = (reservation_id IS NULL)),
            PRIMARY KEY (org_id, project_id, analysis_id, sequence),
            UNIQUE NULLS NOT DISTINCT (org_id, project_id, analysis_id, kind, reservation_id),
            FOREIGN KEY (org_id, project_id, analysis_id)
                REFERENCES pentest_agent.offline_analysis(org_id, project_id, id),
            FOREIGN KEY (org_id, project_id, analysis_id, reservation_id)
                REFERENCES pentest_agent.analysis_reservation(org_id, project_id, analysis_id, id)
        )
    """)
    for name in TABLES:
        table = f"{SCHEMA}.{name}"
        owner = f"actor_id = {ACTOR}" if name == "offline_analysis" else f"""
            EXISTS (SELECT 1 FROM {SCHEMA}.offline_analysis AS a
                    WHERE (a.org_id, a.project_id, a.id) = ({name}.org_id, {name}.project_id, {name}.analysis_id)
                      AND a.actor_id = {ACTOR})
        """
        policy = f"{SCOPE} AND {OPERATOR} AND ({owner})"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {ROLE}")
        op.execute(f"CREATE POLICY owner_read ON {table} FOR SELECT TO {ROLE} USING ({policy})")
        op.execute(f"CREATE POLICY owner_insert ON {table} FOR INSERT TO {ROLE} WITH CHECK ({policy})")

    # The definer can count sessions in the caller's project without exposing other actors' rows.
    op.execute(f"""
        CREATE POLICY analysis_counter_membership ON {SCHEMA}.project_membership FOR SELECT TO CURRENT_USER
        USING ({SCOPE} AND user_id = {ACTOR} AND role_id = 'operator')
    """)
    for name in ("analysis_reservation", "analysis_settlement"):
        op.execute(f"""CREATE POLICY project_counter ON {SCHEMA}.{name} FOR SELECT TO CURRENT_USER
                        USING ({SCOPE} AND {OPERATOR})""")
    op.execute(f"""
        CREATE FUNCTION {SCHEMA}.active_analysis_reservations() RETURNS bigint
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT count(*) FROM {SCHEMA}.analysis_reservation AS r
            WHERE r.org_id = {ORG} AND r.project_id = {PROJECT}
              AND r.expires_at > clock_timestamp()
              AND NOT EXISTS (
                  SELECT 1 FROM {SCHEMA}.analysis_settlement AS s
                  WHERE (s.org_id, s.project_id, s.analysis_id, s.id) = (r.org_id, r.project_id, r.analysis_id, r.id)
              )
        $$
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {SCHEMA}.active_analysis_reservations() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SCHEMA}.active_analysis_reservations() TO {ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SCHEMA}.active_analysis_reservations()")
    op.execute(f"DROP POLICY analysis_counter_membership ON {SCHEMA}.project_membership")
    for name in reversed(TABLES):
        op.drop_table(name, schema=SCHEMA)
