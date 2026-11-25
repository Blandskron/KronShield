"""Audit organization stop changes through a scoped database operation."""

from alembic import op

revision = "0010_organization_stop"
down_revision = "0009_evidence_retention"
branch_labels = None
depends_on = None

SCHEMA = "pentest_agent"
RUNTIME = "pentest_agent_runtime"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
ORG_ADMIN = f"id = {ORG} AND {SCHEMA}.is_org_admin({ORG})"


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE {SCHEMA}.organization
        ADD COLUMN stop_revision bigint NOT NULL DEFAULT 0 CHECK (stop_revision >= 0)
    """)
    op.execute(f"""
        CREATE TABLE {SCHEMA}.organization_stop_event (
            org_id uuid NOT NULL REFERENCES {SCHEMA}.organization(id),
            revision bigint NOT NULL CHECK (revision > 0),
            enabled boolean NOT NULL,
            actor_id uuid NOT NULL REFERENCES {SCHEMA}.identity(id),
            reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (org_id, revision)
        )
    """)
    op.execute(f"ALTER TABLE {SCHEMA}.organization_stop_event ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.organization_stop_event FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT ON {SCHEMA}.organization_stop_event TO {RUNTIME}")
    op.execute(f"""
        CREATE POLICY admin_read ON {SCHEMA}.organization_stop_event FOR SELECT TO {RUNTIME}
        USING (org_id = {ORG} AND {SCHEMA}.is_org_admin({ORG}))
    """)
    op.execute(f"""
        CREATE POLICY write_stop_event ON {SCHEMA}.organization_stop_event FOR INSERT TO CURRENT_USER
        WITH CHECK (org_id = {ORG} AND actor_id = {ACTOR} AND {SCHEMA}.is_org_admin({ORG}))
    """)
    op.execute(f"""
        CREATE POLICY read_for_stop ON {SCHEMA}.organization FOR SELECT TO CURRENT_USER USING ({ORG_ADMIN})
    """)
    op.execute(f"""
        CREATE POLICY update_for_stop ON {SCHEMA}.organization FOR UPDATE TO CURRENT_USER
        USING ({ORG_ADMIN}) WITH CHECK ({ORG_ADMIN})
    """)
    op.execute(f"""
        CREATE FUNCTION {SCHEMA}.update_organization_stop(expected bigint, desired boolean, justification text)
        RETURNS TABLE (enabled boolean, revision bigint)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE current_enabled boolean;
        DECLARE current_revision bigint;
        BEGIN
            IF {SCHEMA}.is_org_admin({ORG}) IS DISTINCT FROM TRUE THEN
                RAISE insufficient_privilege;
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('organization-work/' || {ORG}::text, 0));
            SELECT o.kill_switch, o.stop_revision INTO current_enabled, current_revision
                FROM {SCHEMA}.organization AS o WHERE o.id = {ORG} AND o.state = 'active' FOR UPDATE;
            IF NOT FOUND OR current_revision <> expected THEN
                RETURN;
            END IF;
            IF current_enabled <> desired THEN
                current_revision := current_revision + 1;
                UPDATE {SCHEMA}.organization SET kill_switch = desired, stop_revision = current_revision
                WHERE id = {ORG};
                INSERT INTO {SCHEMA}.organization_stop_event (org_id, revision, enabled, actor_id, reason)
                VALUES ({ORG}, current_revision, desired, {ACTOR}, justification);
            END IF;
            RETURN QUERY SELECT desired, current_revision;
        END;
        $$
    """)
    signature = f"{SCHEMA}.update_organization_stop(bigint, boolean, text)"
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {RUNTIME}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SCHEMA}.update_organization_stop(bigint, boolean, text)")
    op.execute(f"DROP POLICY update_for_stop ON {SCHEMA}.organization")
    op.execute(f"DROP POLICY read_for_stop ON {SCHEMA}.organization")
    op.drop_table("organization_stop_event", schema=SCHEMA)
    op.drop_column("organization", "stop_revision", schema=SCHEMA)
