"""Add tenant-scoped inventory writes, encrypted documents and immutable approvals."""

from alembic import op

revision = "0003_engagements"
down_revision = "0002_authentication"
branch_labels = None
depends_on = None

ROLE = "pentest_agent_runtime"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
USER = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
PLATFORM = f"EXISTS (SELECT 1 FROM pentest_agent.platform_admin AS a WHERE a.user_id = {USER})"
ORG_ADMIN = (
    f"EXISTS (SELECT 1 FROM pentest_agent.organization_membership AS m "
    f"WHERE m.org_id = {ORG} AND m.user_id = {USER} AND m.role_id = 'org_admin')"
)
PROJECT_MEMBER = (
    f"EXISTS (SELECT 1 FROM pentest_agent.project_membership AS m "
    f"WHERE m.org_id = {ORG} AND m.project_id = {PROJECT} AND m.user_id = {USER})"
)
PROJECT_SCOPE = f"org_id = {ORG} AND project_id = {PROJECT} AND {PROJECT_MEMBER}"
OPERATOR = PROJECT_MEMBER.replace("m.user_id =", "m.role_id = 'operator' AND m.user_id =")
APPROVER = PROJECT_MEMBER.replace("m.user_id =", "m.role_id = 'approver' AND m.user_id =")
PROJECT_ADMIN = PROJECT_MEMBER.replace("m.user_id =", "m.role_id = 'project_admin' AND m.user_id =")

CURRENT_PROVISION = "created_xact = pg_current_xact_id_if_assigned()"

POLICIES = (
    ("platform_admin", "personal_read", "SELECT", f"user_id = {USER}"),
    ("organization_membership", "personal_read", "SELECT", f"{ORG} IS NULL AND user_id = {USER}"),
    ("organization", "personal_read", "SELECT", f"""
        {ORG} IS NULL AND EXISTS (
            SELECT 1 FROM pentest_agent.organization_membership AS m
            WHERE m.org_id = organization.id AND m.user_id = {USER}
        )
    """),
    ("organization", "provision_read", "SELECT", f"id = {ORG} AND {PLATFORM} AND {CURRENT_PROVISION}"),
    ("organization", "provision", "INSERT", f"id = {ORG} AND {PLATFORM}"),
    ("organization_membership", "provision_org", "INSERT",
     f"org_id = {ORG} AND user_id <> {USER} AND role_id = 'org_admin' AND {PLATFORM} "
     f"AND EXISTS (SELECT 1 FROM pentest_agent.organization WHERE id = {ORG} AND {CURRENT_PROVISION})"),
    ("organization", "admin_update", "UPDATE", f"id = {ORG} AND {ORG_ADMIN}"),
    ("customer", "admin_insert", "INSERT", f"org_id = {ORG} AND {ORG_ADMIN}"),
    ("customer", "admin_update", "UPDATE", f"org_id = {ORG} AND {ORG_ADMIN}"),
    ("customer", "admin_delete", "DELETE", f"org_id = {ORG} AND {ORG_ADMIN}"),
    ("project", "inventory_read", "SELECT", f"""
        org_id = {ORG} AND {PROJECT} IS NULL AND EXISTS (
            SELECT 1 FROM pentest_agent.project_membership AS m
            WHERE m.org_id = project.org_id AND m.project_id = project.id AND m.user_id = {USER}
        )
    """),
    ("project", "provision_read", "SELECT", f"org_id = {ORG} AND id = {PROJECT} AND {ORG_ADMIN} AND {CURRENT_PROVISION}"),
    ("project", "admin_insert", "INSERT", f"org_id = {ORG} AND id = {PROJECT} AND {ORG_ADMIN}"),
    ("project_membership", "provision_project", "INSERT",
     f"org_id = {ORG} AND project_id = {PROJECT} AND user_id = {USER} "
     f"AND role_id = 'project_admin' AND {ORG_ADMIN} "
     f"AND EXISTS (SELECT 1 FROM pentest_agent.project WHERE org_id = {ORG} AND id = {PROJECT} "
     f"AND {CURRENT_PROVISION})"),
    ("project", "admin_update", "UPDATE", f"org_id = {ORG} AND id = {PROJECT} AND {PROJECT_ADMIN}"),
    ("authorization_document", "restricted_read", "SELECT",
     f"{PROJECT_SCOPE} AND (uploader_id = {USER} OR {APPROVER})"),
    ("authorization_document", "operator_insert", "INSERT",
     f"{PROJECT_SCOPE} AND uploader_id = {USER} AND {OPERATOR}"),
    ("authorization", "operator_insert", "INSERT",
     f"{PROJECT_SCOPE} AND requester_id = {USER} AND status = 'draft' AND verifier_id IS NULL "
     f"AND document_id IS NOT NULL AND {OPERATOR}"),
    ("authorization_decision", "member_read", "SELECT", PROJECT_SCOPE),
    ("authorization_decision", "approver_insert", "INSERT", f"""
        {PROJECT_SCOPE} AND actor_id = {USER} AND {APPROVER}
        AND EXISTS (
            SELECT 1 FROM pentest_agent.authorization AS a
            WHERE (a.org_id, a.project_id, a.id, a.revision) =
                  (authorization_decision.org_id, authorization_decision.project_id,
                   authorization_decision.authorization_id, authorization_decision.revision)
              AND a.requester_id <> {USER}
        )
    """),
)

GRANTS = {
    "platform_admin": "SELECT",
    "organization": "INSERT (id, slug), UPDATE (slug, state, version)",
    "organization_membership": "INSERT",
    "customer": "INSERT, UPDATE (slug, name, version), DELETE",
    "project": "INSERT (org_id, id, customer_id, slug, environment), UPDATE (slug, state, version)",
    "project_membership": "INSERT",
    "authorization_document": "SELECT, INSERT",
    "authorization": "INSERT",
    "authorization_decision": "SELECT, INSERT",
}


def _target_policies(expression: str) -> None:
    op.execute(f"ALTER POLICY tenant_insert ON pentest_agent.target WITH CHECK ({expression})")
    op.execute(f"ALTER POLICY tenant_update ON pentest_agent.target USING ({expression}) WITH CHECK ({expression})")
    op.execute(f"ALTER POLICY tenant_delete ON pentest_agent.target USING ({expression})")


def upgrade() -> None:
    _target_policies(f"{PROJECT_SCOPE} AND {OPERATOR}")
    op.execute("""
        INSERT INTO pentest_agent.role (id) VALUES ('org_admin'), ('project_admin'),
            ('viewer'), ('operator'), ('approver') ON CONFLICT DO NOTHING
    """)
    for table in ("organization", "customer", "project", "target"):
        op.execute(f"ALTER TABLE pentest_agent.{table} ADD COLUMN version bigint NOT NULL DEFAULT 1")
    for table in ("organization", "project"):
        op.execute(f"ALTER TABLE pentest_agent.{table} ADD COLUMN created_xact xid8")
        op.execute(f"ALTER TABLE pentest_agent.{table} ALTER COLUMN created_xact SET DEFAULT pg_current_xact_id()")
    op.execute("ALTER TABLE pentest_agent.target ADD COLUMN third_party_id text")
    op.execute("""
        CREATE TABLE pentest_agent.platform_admin (
            user_id uuid PRIMARY KEY REFERENCES pentest_agent.identity(id)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.authorization_document (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            id uuid NOT NULL,
            uploader_id uuid NOT NULL,
            digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
            nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
            ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 21 AND 1048592),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, project_id, id),
            UNIQUE (org_id, project_id, id, digest),
            FOREIGN KEY (org_id, project_id) REFERENCES pentest_agent.project(org_id, id),
            FOREIGN KEY (org_id, uploader_id) REFERENCES pentest_agent.organization_membership(org_id, user_id)
        )
    """)
    op.execute("""
        ALTER TABLE pentest_agent.authorization
          ADD COLUMN document_id uuid,
          ADD COLUMN scope_rules jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(scope_rules) = 'array'),
          ADD COLUMN limits jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(limits) = 'object'),
          ADD CONSTRAINT authorization_document_scope FOREIGN KEY (org_id, project_id, document_id, document_digest)
            REFERENCES pentest_agent.authorization_document(org_id, project_id, id, digest)
    """)
    op.execute("""
        CREATE TABLE pentest_agent.authorization_decision (
            org_id uuid NOT NULL,
            project_id uuid NOT NULL,
            authorization_id uuid NOT NULL,
            revision integer NOT NULL,
            decision text NOT NULL CHECK (decision IN ('approve', 'revoke')),
            actor_id uuid NOT NULL,
            reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, project_id, authorization_id, revision, decision),
            FOREIGN KEY (org_id, project_id, authorization_id, revision)
                REFERENCES pentest_agent.authorization(org_id, project_id, id, revision),
            FOREIGN KEY (org_id, actor_id) REFERENCES pentest_agent.organization_membership(org_id, user_id)
        )
    """)
    for table in ("platform_admin", "authorization_document", "authorization_decision"):
        op.execute(f"ALTER TABLE pentest_agent.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pentest_agent.{table} FORCE ROW LEVEL SECURITY")
    for table, grants in GRANTS.items():
        op.execute(f"GRANT {grants} ON pentest_agent.{table} TO {ROLE}")
    for table, policy, action, expression in POLICIES:
        clause = f"WITH CHECK ({expression})" if action == "INSERT" else f"USING ({expression})"
        op.execute(f"CREATE POLICY {policy} ON pentest_agent.{table} FOR {action} TO {ROLE} {clause}")


def downgrade() -> None:
    _target_policies(PROJECT_SCOPE)
    for table, policy, _, _ in reversed(POLICIES):
        op.execute(f"DROP POLICY {policy} ON pentest_agent.{table}")
    for table, grants in GRANTS.items():
        op.execute(f"REVOKE {grants} ON pentest_agent.{table} FROM {ROLE}")
    op.drop_table("authorization_decision", schema="pentest_agent")
    op.execute("""
        ALTER TABLE pentest_agent.authorization DROP CONSTRAINT authorization_document_scope,
          DROP COLUMN document_id, DROP COLUMN scope_rules, DROP COLUMN limits
    """)
    op.drop_table("authorization_document", schema="pentest_agent")
    op.drop_table("platform_admin", schema="pentest_agent")
    op.execute("ALTER TABLE pentest_agent.target DROP COLUMN third_party_id")
    for table in ("organization", "project"):
        op.execute(f"ALTER TABLE pentest_agent.{table} DROP COLUMN created_xact")
    for table in ("organization", "customer", "project", "target"):
        op.execute(f"ALTER TABLE pentest_agent.{table} DROP COLUMN version")
