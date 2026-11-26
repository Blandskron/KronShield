"""Isolate human decisions and immutable analysis reports."""

from alembic import op

revision = "0014_analysis_publication"
down_revision = "0013_analysis_lifecycle"
branch_labels = None
depends_on = None

SCHEMA = "pentest_agent"
ROLE = "pentest_agent_runtime"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
SCOPE = f"org_id = {ORG} AND project_id = {PROJECT}"
MEMBERSHIP = f"""SELECT 1 FROM {SCHEMA}.project_membership AS m
                 WHERE m.org_id = {ORG} AND m.project_id = {PROJECT} AND m.user_id = {ACTOR}"""
APPROVER = f"EXISTS ({MEMBERSHIP} AND m.role_id = 'approver')"
EVIDENCE_POLICIES = (
    ("evidence_permission", "member_read"),
    ("evidence_decision", "member_read"),
    ("evidence_disposition", "permission_read"),
)


def upgrade() -> None:
    op.execute(f"""
        CREATE FUNCTION {SCHEMA}.lock_analysis_membership_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE authority_key text;
        BEGIN
            FOR authority_key IN
                SELECT DISTINCT key FROM unnest(ARRAY[
                    CASE WHEN TG_OP <> 'INSERT' THEN 'analysis-membership/' || OLD.org_id || '/' || OLD.user_id END,
                    CASE WHEN TG_OP <> 'DELETE' THEN 'analysis-membership/' || NEW.org_id || '/' || NEW.user_id END
                ]) AS key WHERE key IS NOT NULL ORDER BY key
            LOOP
                PERFORM pg_advisory_xact_lock(hashtextextended(authority_key, 0));
            END LOOP;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END
        $$
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {SCHEMA}.lock_analysis_membership_change() FROM PUBLIC")
    for table in ("project_membership", "organization_membership"):
        op.execute(f"""
            CREATE TRIGGER protect_analysis_membership BEFORE INSERT OR UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.lock_analysis_membership_change()
        """)
    op.execute(f"""
        CREATE POLICY analysis_reviewer_membership ON {SCHEMA}.project_membership
            FOR SELECT TO CURRENT_USER USING ({SCOPE} AND user_id = {ACTOR} AND role_id = 'approver')
    """)
    for table, policy in EVIDENCE_POLICIES:
        op.execute(f"ALTER POLICY {policy} ON {SCHEMA}.{table} TO {ROLE}, CURRENT_USER")

    op.execute(f"""
        CREATE FUNCTION {SCHEMA}.analysis_evidence_visible(permission uuid, revision_no integer, sources jsonb)
        RETURNS boolean LANGUAGE sql VOLATILE SET search_path = pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1 FROM {SCHEMA}.evidence_permission AS p
                JOIN {SCHEMA}.evidence_decision AS a
                  ON (a.org_id, a.project_id, a.permission_id, a.revision) = (p.org_id, p.project_id, p.id, p.revision)
                 AND a.kind = 'approve'
                JOIN {SCHEMA}.project_membership AS m
                  ON (m.org_id, m.project_id, m.user_id) = (p.org_id, p.project_id, {ACTOR})
                WHERE p.org_id = {ORG} AND p.project_id = {PROJECT} AND p.id = permission AND p.revision = revision_no
                  AND ((m.role_id = 'operator' AND p.requester_id = {ACTOR})
                    OR (m.role_id = 'approver' AND a.actor_id = {ACTOR}))
                  AND clock_timestamp() >= (p.spec->>'valid_from')::timestamptz
                  AND clock_timestamp() < (p.spec->>'valid_until')::timestamptz
                  AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.evidence_permission AS newer
                      WHERE (newer.org_id, newer.project_id, newer.id) = (p.org_id, p.project_id, p.id)
                        AND newer.revision > p.revision)
                  AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.evidence_decision AS r
                      WHERE (r.org_id, r.project_id, r.permission_id, r.revision) =
                            (p.org_id, p.project_id, p.id, p.revision) AND r.kind = 'revoke')
                  AND jsonb_array_length(sources) > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM jsonb_array_elements(sources) AS frozen
                      WHERE NOT EXISTS (
                          SELECT 1 FROM jsonb_array_elements(p.spec->'sources') AS source
                          WHERE source->>'digest' = frozen->>'digest'
                            AND clock_timestamp() < {SCHEMA}.evidence_retention_until(p.spec, source)
                      ) OR EXISTS (SELECT 1 FROM {SCHEMA}.evidence_disposition AS d
                          WHERE (d.org_id, d.project_id, d.permission_id, d.revision) =
                                (p.org_id, p.project_id, p.id, p.revision) AND d.source_digest = frozen->>'digest')
                  )
            )
        $$
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {SCHEMA}.analysis_evidence_visible(uuid, integer, jsonb) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SCHEMA}.analysis_evidence_visible(uuid, integer, jsonb) TO {ROLE}")
    op.execute(f"""
        CREATE POLICY designated_analysis_reviewer ON {SCHEMA}.offline_analysis FOR SELECT TO CURRENT_USER USING (
            {SCOPE} AND {APPROVER} AND actor_id <> {ACTOR}
            AND {SCHEMA}.analysis_evidence_visible(permission_id, permission_revision, snapshot->'sources')
        )
    """)
    for table in ("analysis_step_outcome", "analysis_cancellation"):
        op.execute(f"""
            CREATE POLICY designated_analysis_reviewer ON {SCHEMA}.{table} FOR SELECT TO CURRENT_USER USING (
                {SCOPE} AND EXISTS (SELECT 1 FROM {SCHEMA}.offline_analysis AS a
                    WHERE (a.org_id, a.project_id, a.id) = ({table}.org_id, {table}.project_id, {table}.analysis_id))
            )
        """)
    op.execute(f"""
        CREATE FUNCTION {SCHEMA}.analysis_review_input(review_id uuid)
        RETURNS TABLE (author_id uuid, snapshot_digest text, snapshot jsonb, cancelled boolean, outcomes jsonb)
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT a.actor_id, a.snapshot_digest, a.snapshot, lifecycle.cancelled,
                CASE WHEN NOT lifecycle.cancelled AND steps.complete THEN steps.outcomes ELSE '[]'::jsonb END
            FROM {SCHEMA}.offline_analysis AS a
            CROSS JOIN LATERAL (
                SELECT EXISTS (SELECT 1 FROM {SCHEMA}.analysis_cancellation AS c
                    WHERE (c.org_id, c.project_id, c.analysis_id) = (a.org_id, a.project_id, a.id)) AS cancelled
            ) AS lifecycle
            CROSS JOIN LATERAL (
                SELECT count(*) = jsonb_array_length(a.snapshot->'manifest'->'workflow')
                           AND bool_and(s.state = 'completed') AS complete,
                       jsonb_agg(jsonb_build_object('step_id', s.step_id, 'state', s.state,
                           'output', s.output, 'proposal_receipt', s.proposal_receipt)
                           ORDER BY s.step_id, s.created_at) AS outcomes
                FROM {SCHEMA}.analysis_step_outcome AS s
                WHERE (s.org_id, s.project_id, s.analysis_id) = (a.org_id, a.project_id, a.id)
            ) AS steps
            WHERE a.org_id = {ORG} AND a.project_id = {PROJECT} AND a.id = review_id
              AND {APPROVER} AND a.actor_id <> {ACTOR}
              AND {SCHEMA}.analysis_evidence_visible(a.permission_id, a.permission_revision, a.snapshot->'sources')
        $$
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {SCHEMA}.analysis_review_input(uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SCHEMA}.analysis_review_input(uuid) TO {ROLE}")

    op.execute(f"""
        CREATE TABLE {SCHEMA}.analysis_review_decision (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            analysis_id uuid NOT NULL,
            conclusion_id text NOT NULL CHECK (conclusion_id ~ '^[a-z][a-z0-9-]{{0,63}}[.](observation|draft)$'),
            actor_id uuid NOT NULL REFERENCES {SCHEMA}.identity(id),
            decision text NOT NULL CHECK (decision IN ('approve', 'reject')),
            reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
            decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (org_id, project_id, analysis_id, conclusion_id),
            FOREIGN KEY (org_id, project_id, analysis_id) REFERENCES {SCHEMA}.offline_analysis(org_id, project_id, id)
        )
    """)
    op.execute(f"""
        CREATE TABLE {SCHEMA}.analysis_publication (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            analysis_id uuid NOT NULL,
            actor_id uuid NOT NULL REFERENCES {SCHEMA}.identity(id),
            permission_id uuid NOT NULL,
            permission_revision integer NOT NULL,
            snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
            sources jsonb NOT NULL CHECK (jsonb_typeof(sources) = 'array'),
            report bytea NOT NULL CHECK (octet_length(report) BETWEEN 1 AND 1048576),
            report_digest text NOT NULL CHECK (report_digest ~ '^[a-f0-9]{{64}}$'),
            published_at timestamptz NOT NULL,
            PRIMARY KEY (org_id, project_id, analysis_id),
            FOREIGN KEY (org_id, project_id, analysis_id) REFERENCES {SCHEMA}.offline_analysis(org_id, project_id, id),
            FOREIGN KEY (org_id, project_id, permission_id, permission_revision)
                REFERENCES {SCHEMA}.evidence_permission(org_id, project_id, id, revision)
        )
    """)
    reviewer = f"""EXISTS (SELECT 1 FROM {SCHEMA}.analysis_review_input(analysis_id) AS a
                           WHERE NOT a.cancelled AND jsonb_array_length(a.outcomes) > 0)"""
    for table in ("analysis_review_decision", "analysis_publication"):
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.{table} TO {ROLE}")
    op.execute(f"""
        CREATE POLICY reviewer_read ON {SCHEMA}.analysis_review_decision FOR SELECT TO {ROLE}
        USING ({SCOPE} AND {reviewer})
    """)
    op.execute(f"""
        CREATE POLICY reviewer_write ON {SCHEMA}.analysis_review_decision FOR INSERT TO {ROLE}
        WITH CHECK ({SCOPE} AND {APPROVER} AND actor_id = {ACTOR} AND {reviewer})
    """)
    op.execute(f"""
        CREATE POLICY evidence_reader ON {SCHEMA}.analysis_publication FOR SELECT TO {ROLE}
        USING ({SCOPE} AND {SCHEMA}.analysis_evidence_visible(permission_id, permission_revision, sources))
    """)
    op.execute(f"""
        CREATE POLICY reviewer_publish ON {SCHEMA}.analysis_publication FOR INSERT TO {ROLE}
        WITH CHECK ({SCOPE} AND {APPROVER} AND actor_id = {ACTOR} AND EXISTS (
            SELECT 1 FROM {SCHEMA}.analysis_review_input(analysis_id) AS a WHERE NOT a.cancelled
                AND jsonb_array_length(a.outcomes) > 0
                AND a.snapshot->>'permission_id' = permission_id::text
                AND (a.snapshot->>'permission_revision')::integer = permission_revision
                AND a.snapshot->'sources' = sources))
    """)


def downgrade() -> None:
    op.drop_table("analysis_publication", schema=SCHEMA)
    op.drop_table("analysis_review_decision", schema=SCHEMA)
    op.execute(f"DROP FUNCTION {SCHEMA}.analysis_review_input(uuid)")
    for table in ("analysis_step_outcome", "analysis_cancellation", "offline_analysis"):
        op.execute(f"DROP POLICY designated_analysis_reviewer ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.analysis_evidence_visible(uuid, integer, jsonb)")
    for table, policy in EVIDENCE_POLICIES:
        op.execute(f"ALTER POLICY {policy} ON {SCHEMA}.{table} TO {ROLE}")
    op.execute(f"DROP POLICY analysis_reviewer_membership ON {SCHEMA}.project_membership")
    for table in ("project_membership", "organization_membership"):
        op.execute(f"DROP TRIGGER protect_analysis_membership ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.lock_analysis_membership_change()")
