"""Enforce evidence retention and record immutable dispositions."""

from alembic import op

revision = "0009_evidence_retention"
down_revision = "0008_evidence_permissions"
branch_labels = None
depends_on = None

SCHEMA = "pentest_agent"
RUNTIME = "pentest_agent_runtime"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
TABLE = f"{SCHEMA}.evidence_disposition"
SCOPE = f"org_id = {ORG} AND project_id = {PROJECT}"
PARENT = f"""
    SELECT 1 FROM {SCHEMA}.evidence_permission AS p
    WHERE (p.org_id, p.project_id, p.id, p.revision) =
          (evidence_disposition.org_id, evidence_disposition.project_id,
           evidence_disposition.permission_id, evidence_disposition.revision)
    AND p.spec->'sources' @> jsonb_build_array(jsonb_build_object('digest', evidence_disposition.source_digest))
"""


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE {TABLE} (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            permission_id uuid NOT NULL,
            revision integer NOT NULL,
            source_digest text NOT NULL CHECK (source_digest ~ '^[0-9a-f]{{64}}$'),
            kind text NOT NULL CHECK (kind IN ('expired', 'withdrawn')),
            actor_id uuid,
            reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK ((kind = 'expired') = (actor_id IS NULL)),
            PRIMARY KEY (org_id, project_id, permission_id, revision, source_digest),
            FOREIGN KEY (org_id, project_id, permission_id, revision)
                REFERENCES {SCHEMA}.evidence_permission(org_id, project_id, id, revision)
        )
    """)
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {RUNTIME}")
    op.execute(f"""
        CREATE POLICY permission_read ON {TABLE} FOR SELECT TO {RUNTIME}
        USING ({SCOPE} AND EXISTS ({PARENT}))
    """)
    op.execute(f"""
        CREATE POLICY approver_withdraw ON {TABLE} FOR INSERT TO {RUNTIME}
        WITH CHECK (
            {SCOPE} AND kind = 'withdrawn' AND actor_id = {ACTOR}
            AND EXISTS ({PARENT} AND p.requester_id <> {ACTOR})
            AND EXISTS (SELECT 1 FROM {SCHEMA}.project_membership AS m
                        WHERE m.org_id = {ORG} AND m.project_id = {PROJECT}
                          AND m.user_id = {ACTOR} AND m.role_id = 'approver')
        )
    """)
    op.execute(f"""
        CREATE FUNCTION {SCHEMA}.evidence_retention_until(spec jsonb, source jsonb) RETURNS timestamptz
        LANGUAGE sql STABLE SET search_path = pg_catalog
        AS $$
            SELECT LEAST(
                (spec->>'valid_until')::timestamptz,
                (source->>'retain_until')::timestamptz,
                (spec->>'valid_from')::timestamptz + CASE source->>'classification'
                    WHEN 'restricted' THEN interval '168 hours' ELSE interval '720 hours' END
            )
        $$
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {SCHEMA}.evidence_retention_until(jsonb, jsonb) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SCHEMA}.evidence_retention_until(jsonb, jsonb) TO {RUNTIME}")
    op.execute(f"""
        CREATE POLICY retained_projection ON {SCHEMA}.evidence_projection AS RESTRICTIVE TO {RUNTIME}
        USING (
            NOT EXISTS (SELECT 1 FROM {TABLE} AS d
                WHERE (d.org_id, d.project_id, d.permission_id, d.revision, d.source_digest) =
                    (evidence_projection.org_id, evidence_projection.project_id, evidence_projection.permission_id,
                     evidence_projection.revision, evidence_projection.source_digest))
            AND EXISTS (SELECT 1 FROM {SCHEMA}.evidence_permission AS p,
                        LATERAL jsonb_array_elements(p.spec->'sources') AS source
                WHERE (p.org_id, p.project_id, p.id, p.revision) =
                    (evidence_projection.org_id, evidence_projection.project_id, evidence_projection.permission_id,
                     evidence_projection.revision)
                  AND source->>'digest' = evidence_projection.source_digest
                  AND clock_timestamp() < {SCHEMA}.evidence_retention_until(p.spec, source))
        )
    """)
    op.execute(f"""
        CREATE FUNCTION {SCHEMA}.sweep_evidence_retention() RETURNS integer
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE purged integer;
        BEGIN
            INSERT INTO {TABLE} (org_id, project_id, permission_id, revision, source_digest, kind, reason)
            SELECT p.org_id, p.project_id, p.id, p.revision, source->>'digest', 'expired', 'retention_elapsed'
            FROM {SCHEMA}.evidence_permission AS p, LATERAL jsonb_array_elements(p.spec->'sources') AS source
            WHERE clock_timestamp() >= {SCHEMA}.evidence_retention_until(p.spec, source)
            ON CONFLICT DO NOTHING;
            DELETE FROM {SCHEMA}.evidence_projection AS e USING {TABLE} AS d
            WHERE (e.org_id, e.project_id, e.permission_id, e.revision, e.source_digest) =
                  (d.org_id, d.project_id, d.permission_id, d.revision, d.source_digest);
            GET DIAGNOSTICS purged = ROW_COUNT;
            RETURN purged;
        END;
        $$
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {SCHEMA}.sweep_evidence_retention() FROM PUBLIC")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SCHEMA}.sweep_evidence_retention()")
    op.execute(f"DROP POLICY retained_projection ON {SCHEMA}.evidence_projection")
    op.execute(f"DROP FUNCTION {SCHEMA}.evidence_retention_until(jsonb, jsonb)")
    op.drop_table("evidence_disposition", schema=SCHEMA)
