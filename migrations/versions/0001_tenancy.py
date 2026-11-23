"""Create the organization and project schema with PostgreSQL row security."""

from alembic import op
from sqlalchemy import text

revision = "0001_tenancy"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "pentest_agent"
ROLE = "pentest_agent_runtime"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
USER = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"

TABLES = {
    "organization": """
        id uuid PRIMARY KEY,
        slug text NOT NULL UNIQUE,
        state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'suspended')),
        retention_days integer CHECK (retention_days > 0),
        kill_switch boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now()
    """,
    "identity": """
        id uuid PRIMARY KEY,
        issuer text NOT NULL,
        subject text NOT NULL,
        UNIQUE (issuer, subject)
    """,
    "role": """
        id text PRIMARY KEY
    """,
    "organization_membership": """
        org_id uuid NOT NULL REFERENCES pentest_agent.organization (id),
        user_id uuid NOT NULL REFERENCES pentest_agent.identity (id),
        role_id text NOT NULL REFERENCES pentest_agent.role (id),
        PRIMARY KEY (org_id, user_id)
    """,
    "customer": """
        org_id uuid NOT NULL REFERENCES pentest_agent.organization (id),
        id uuid NOT NULL,
        slug text NOT NULL,
        name text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (org_id, id),
        UNIQUE (org_id, slug)
    """,
    "project": """
        org_id uuid NOT NULL,
        id uuid NOT NULL,
        customer_id uuid NOT NULL,
        slug text NOT NULL,
        environment text NOT NULL,
        state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'archived')),
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (org_id, id),
        UNIQUE (org_id, slug),
        FOREIGN KEY (org_id, customer_id) REFERENCES pentest_agent.customer (org_id, id)
    """,
    "project_membership": """
        org_id uuid NOT NULL,
        project_id uuid NOT NULL,
        user_id uuid NOT NULL,
        role_id text NOT NULL REFERENCES pentest_agent.role (id),
        PRIMARY KEY (org_id, project_id, user_id),
        FOREIGN KEY (org_id, project_id) REFERENCES pentest_agent.project (org_id, id),
        FOREIGN KEY (org_id, user_id) REFERENCES pentest_agent.organization_membership (org_id, user_id)
    """,
    "authorization": """
        org_id uuid NOT NULL,
        project_id uuid NOT NULL,
        id uuid NOT NULL,
        revision integer NOT NULL CHECK (revision > 0),
        requester_id uuid NOT NULL,
        delegator_id uuid NOT NULL,
        verifier_id uuid,
        document_reference text NOT NULL,
        document_digest text NOT NULL CHECK (document_digest ~ '^[0-9a-f]{64}$'),
        status text NOT NULL CHECK (status IN ('draft', 'approved', 'revoked')),
        environment text NOT NULL,
        valid_from timestamptz NOT NULL,
        valid_until timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (org_id, project_id, id, revision),
        FOREIGN KEY (org_id, project_id) REFERENCES pentest_agent.project (org_id, id),
        FOREIGN KEY (org_id, requester_id) REFERENCES pentest_agent.organization_membership (org_id, user_id),
        FOREIGN KEY (org_id, delegator_id) REFERENCES pentest_agent.organization_membership (org_id, user_id),
        FOREIGN KEY (org_id, verifier_id) REFERENCES pentest_agent.organization_membership (org_id, user_id),
        CHECK (valid_from < valid_until),
        CHECK (status <> 'approved' OR (verifier_id IS NOT NULL AND verifier_id <> requester_id))
    """,
    "scope": """
        org_id uuid NOT NULL,
        project_id uuid NOT NULL,
        authorization_id uuid NOT NULL,
        authorization_revision integer NOT NULL,
        id uuid NOT NULL,
        effect text NOT NULL CHECK (effect IN ('allow', 'deny')),
        destination_kind text NOT NULL CHECK (destination_kind IN ('fqdn', 'subdomain', 'ip', 'cidr', 'application')),
        destination text NOT NULL,
        constraints jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(constraints) = 'object'),
        PRIMARY KEY (org_id, project_id, authorization_id, authorization_revision, id),
        FOREIGN KEY (org_id, project_id, authorization_id, authorization_revision)
            REFERENCES pentest_agent.authorization (org_id, project_id, id, revision)
    """,
    "target": """
        org_id uuid NOT NULL,
        project_id uuid NOT NULL,
        id uuid NOT NULL,
        slug text NOT NULL,
        environment text NOT NULL,
        canonical_address text NOT NULL,
        attribution text NOT NULL CHECK (attribution IN ('first_party', 'third_party', 'shared', 'unknown')),
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (org_id, project_id, id),
        UNIQUE (org_id, project_id, slug),
        UNIQUE (org_id, project_id, environment, canonical_address),
        FOREIGN KEY (org_id, project_id) REFERENCES pentest_agent.project (org_id, id)
    """,
}


def _verify_role() -> None:
    valid = op.get_bind().execute(text("""
        SELECT NOT (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb
                    OR rolreplication OR rolcanlogin)
               AND NOT pg_has_role(oid, current_user, 'MEMBER')
        FROM pg_roles WHERE rolname = :role
    """), {"role": ROLE}).scalar()
    if not valid:
        raise RuntimeError(f"Provision {ROLE} as a non-privileged NOLOGIN role before migrating")


def _policy(table: str, expression: str, *, write: bool = False) -> None:
    qualified = f"{SCHEMA}.{table}"
    op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT ON {qualified} TO {ROLE}")
    op.execute(f"CREATE POLICY tenant_read ON {qualified} FOR SELECT TO {ROLE} USING ({expression})")
    if write:
        op.execute(f"GRANT INSERT, UPDATE, DELETE ON {qualified} TO {ROLE}")
        op.execute(f"CREATE POLICY tenant_insert ON {qualified} FOR INSERT TO {ROLE} WITH CHECK ({expression})")
        op.execute(f"CREATE POLICY tenant_update ON {qualified} FOR UPDATE TO {ROLE} "
                   f"USING ({expression}) WITH CHECK ({expression})")
        op.execute(f"CREATE POLICY tenant_delete ON {qualified} FOR DELETE TO {ROLE} USING ({expression})")


def upgrade() -> None:
    _verify_role()
    op.execute(f"CREATE SCHEMA {SCHEMA}")
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE}")
    for table, columns in TABLES.items():
        op.execute(f"CREATE TABLE {SCHEMA}.{table} ({columns})")

    _policy("identity", f"id = {USER}")
    op.execute(f"GRANT SELECT ON {SCHEMA}.role TO {ROLE}")
    _policy("organization_membership", f"org_id = {ORG} AND user_id = {USER}")
    _policy("project_membership", f"org_id = {ORG} AND user_id = {USER}")

    org_membership = f"EXISTS (SELECT 1 FROM {SCHEMA}.organization_membership AS m WHERE m.org_id = {ORG})"
    project_membership = (
        f"EXISTS (SELECT 1 FROM {SCHEMA}.project_membership AS m "
        f"WHERE m.org_id = {ORG} AND m.project_id = {PROJECT})"
    )
    _policy("organization", f"id = {ORG} AND {org_membership}")
    _policy("customer", f"org_id = {ORG} AND {org_membership}")
    _policy("project", f"org_id = {ORG} AND id = {PROJECT} AND {project_membership}")
    for table in ("authorization", "scope", "target"):
        _policy(table, f"org_id = {ORG} AND project_id = {PROJECT} AND {project_membership}",
                write=table == "target")


def downgrade() -> None:
    # These read policies depend on membership tables that are removed first.
    for table in ("organization", "project"):
        op.execute(f"DROP POLICY tenant_read ON {SCHEMA}.{table}")
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"DROP SCHEMA {SCHEMA}")
