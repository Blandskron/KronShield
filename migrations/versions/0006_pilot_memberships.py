"""Enable scoped membership administration and explicitly configured pilot identities."""

from alembic import op

revision = "0006_pilot_memberships"
down_revision = "0005_legacy_import"
branch_labels = None
depends_on = None

ROLE = "pentest_agent_runtime"
ACTOR = "NULLIF(current_setting('pentest_agent.user_id', true), '')::uuid"
ORG = "NULLIF(current_setting('pentest_agent.org_id', true), '')::uuid"
PROJECT = "NULLIF(current_setting('pentest_agent.project_id', true), '')::uuid"
ENROLL = "NULLIF(current_setting('pentest_agent.pilot_enroll', true), '')::uuid"
MODE = "current_setting('pentest_agent.manage_memberships', true) = 'on'"
ADMIN = f"{MODE} AND pentest_agent.is_org_admin({ORG})"

POLICIES = (
    ("organization_membership", "manager_read", "SELECT", f"org_id = {ORG} AND {ADMIN}"),
    ("organization_membership", "manager_insert", "INSERT",
     f"org_id = {ORG} AND {ADMIN} AND user_id <> {ACTOR} AND role_id IN ('member', 'org_admin')"),
    ("organization_membership", "manager_update", "UPDATE",
     f"org_id = {ORG} AND {ADMIN} AND user_id <> {ACTOR}"),
    ("organization_membership", "manager_delete", "DELETE", f"org_id = {ORG} AND {ADMIN} AND user_id <> {ACTOR}"),
    ("project", "membership_manager_read", "SELECT", f"org_id = {ORG} AND id = {PROJECT} AND {ADMIN}"),
    ("project_membership", "manager_read", "SELECT", f"org_id = {ORG} AND project_id = {PROJECT} AND {ADMIN}"),
    ("project_membership", "manager_insert", "INSERT",
     f"org_id = {ORG} AND project_id = {PROJECT} AND {ADMIN} AND user_id <> {ACTOR}"),
    ("project_membership", "manager_update", "UPDATE",
     f"org_id = {ORG} AND project_id = {PROJECT} AND {ADMIN} AND user_id <> {ACTOR}"),
    ("project_membership", "manager_delete", "DELETE",
     f"org_id = {ORG} AND project_id = {PROJECT} AND {ADMIN} AND user_id <> {ACTOR}"),
    ("identity", "pilot_insert", "INSERT", f"id = {ENROLL} AND issuer = 'urn:pentest-agent:pilot'"),
    ("platform_admin", "pilot_initial_admin", "INSERT",
     f"user_id = {ENROLL} AND current_setting('pentest_agent.pilot_bootstrap', true) = 'on'"),
    ("pilot_account", "login_lookup", "SELECT", "username = current_setting('pentest_agent.pilot_username', true)"),
    ("pilot_account", "enroll", "INSERT", f"user_id = {ENROLL}"),
    ("pilot_token", "token_read", "SELECT", "digest = current_setting('pentest_agent.pilot_digest', true)"),
    ("pilot_token", "token_revoke", "DELETE", "digest = current_setting('pentest_agent.pilot_digest', true)"),
    ("pilot_token", "token_issue", "INSERT", f"user_id = {ACTOR} AND digest = "
                                             "current_setting('pentest_agent.pilot_digest', true)"),
)


def upgrade() -> None:
    op.execute("INSERT INTO pentest_agent.role (id) VALUES ('member') ON CONFLICT DO NOTHING")
    op.execute(f"""
        CREATE POLICY manager_lookup ON pentest_agent.organization_membership FOR SELECT TO CURRENT_USER
        USING (org_id = {ORG} AND user_id = {ACTOR} AND role_id = 'org_admin')
    """)
    op.execute(f"""
        CREATE FUNCTION pentest_agent.is_org_admin(organization_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
        AS $$
            SELECT organization_id = {ORG} AND EXISTS (
                SELECT 1 FROM pentest_agent.organization_membership
                WHERE org_id = organization_id AND user_id = {ACTOR} AND role_id = 'org_admin'
            )
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION pentest_agent.is_org_admin(uuid) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION pentest_agent.is_org_admin(uuid) TO {ROLE}")
    op.execute("""
        CREATE TABLE pentest_agent.pilot_account (
            user_id uuid PRIMARY KEY REFERENCES pentest_agent.identity(id),
            username text NOT NULL UNIQUE CHECK (username ~ '^[a-z][a-z0-9_-]{2,31}$'),
            salt bytea NOT NULL CHECK (octet_length(salt) = 16),
            password_hash bytea NOT NULL CHECK (octet_length(password_hash) = 32)
        )
    """)
    op.execute("""
        CREATE TABLE pentest_agent.pilot_token (
            digest text PRIMARY KEY CHECK (digest ~ '^[0-9a-f]{64}$'),
            user_id uuid NOT NULL REFERENCES pentest_agent.pilot_account(user_id),
            username text NOT NULL,
            expires_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX pilot_token_expiry ON pentest_agent.pilot_token(expires_at)")
    op.execute("CREATE TABLE pentest_agent.pilot_bootstrap (redeemed boolean PRIMARY KEY CHECK (redeemed))")
    for name in ("pilot_account", "pilot_token", "pilot_bootstrap"):
        op.execute(f"ALTER TABLE pentest_agent.{name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pentest_agent.{name} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT ON pentest_agent.{name} TO {ROLE}")
    op.execute(f"CREATE POLICY single_use ON pentest_agent.pilot_bootstrap TO {ROLE} "
               "USING (current_setting('pentest_agent.pilot_bootstrap', true) = 'on')")
    op.execute(f"GRANT DELETE ON pentest_agent.pilot_token TO {ROLE}")
    op.execute(f"GRANT INSERT ON pentest_agent.identity, pentest_agent.platform_admin TO {ROLE}")
    for name in ("organization_membership", "project_membership"):
        op.execute(f"GRANT UPDATE (role_id), DELETE ON pentest_agent.{name} TO {ROLE}")
    for table, name, action, condition in POLICIES:
        if action == "INSERT":
            clause = f"WITH CHECK ({condition})"
        elif action == "UPDATE":
            roles = "'member', 'org_admin'" if table == "organization_membership" else "'viewer', 'operator', 'approver', 'project_admin'"
            clause = f"USING ({condition}) WITH CHECK ({condition} AND role_id IN ({roles}))"
        else:
            clause = f"USING ({condition})"
        if table == "project_membership" and action == "INSERT" and name == "manager_insert":
            clause = f"WITH CHECK ({condition} AND role_id IN ('viewer', 'operator', 'approver', 'project_admin'))"
        op.execute(f"CREATE POLICY {name} ON pentest_agent.{table} FOR {action} TO {ROLE} {clause}")


def downgrade() -> None:
    for table, name, _, _ in reversed(POLICIES):
        op.execute(f"DROP POLICY {name} ON pentest_agent.{table}")
    for name in ("organization_membership", "project_membership"):
        op.execute(f"REVOKE UPDATE (role_id), DELETE ON pentest_agent.{name} FROM {ROLE}")
    op.execute(f"REVOKE INSERT ON pentest_agent.identity, pentest_agent.platform_admin FROM {ROLE}")
    op.execute("DROP FUNCTION pentest_agent.is_org_admin(uuid)")
    op.execute("DROP POLICY manager_lookup ON pentest_agent.organization_membership")
    for name in ("pilot_bootstrap", "pilot_token", "pilot_account"):
        op.drop_table(name, schema="pentest_agent")
