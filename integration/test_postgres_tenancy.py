"""Exercise the migration against a disposable PostgreSQL database."""

import asyncio
import json
import os
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from threading import Event
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import DBAPIError

from adapters.api.app import build_app
from adapters.api.auth import LOGIN_COOKIE, SESSION_COOKIE, RequestAuth
from adapters.api.contract import SCHEMA_REVISION
from application.access import AccessError, Action
from application.analysis_dispatch import StepOutput, dispatch_step
from application.analysis_proposals import ModelVersion, ProposalDependencyMissing, ProviderReply, generate_proposal
from application.analyses import AnalysisDraft, Usage
from application.authentication import Authentication, Identity
from application.documents import MAX_DOCUMENT_SIZE, DocumentCipher
from application.evidence import PermissionSpec
from domain.team_modes import TEAM_CATALOG, TeamId, ToolId
from infra import analyses, evidence
from infra.analysis_dispatch import PostgresDispatch
from infra.evidence import analysis_context
from infra.auth_store import PostgresAuthStore
from infra.tenancy import tenant_transaction


TARGETS = text("SELECT slug FROM pentest_agent.target ORDER BY slug")
INSERT_TARGET = text("""
    INSERT INTO pentest_agent.target (org_id, project_id, id, slug, environment, canonical_address, attribution)
    VALUES (:org, :project, :id, :slug, 'lab', :address, 'first_party')
""")


def create_target(connection, org, project, slug):
    connection.execute(INSERT_TARGET, {
        "org": org, "project": project, "id": uuid4(), "slug": slug, "address": f"{slug}.example",
    })


@pytest.fixture(scope="module")
def database():
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield from _database(monkeypatch)


def _database(monkeypatch):
    raw_url = os.getenv("PENTEST_AGENT_TEST_POSTGRES_ADMIN_URL")
    if not raw_url:
        pytest.skip("Set PENTEST_AGENT_TEST_POSTGRES_ADMIN_URL to a disposable, empty database")

    admin_url = make_url(raw_url)
    admin = create_engine(admin_url)
    migrator = "pentest_fixture_migrator"
    login = "pentest_fixture_runtime"
    password = uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f"CREATE ROLE {migrator} LOGIN PASSWORD '{password}'"))
        connection.execute(text(f"CREATE ROLE {login} LOGIN PASSWORD '{password}'"))
        connection.execute(text(f"GRANT CREATE ON SCHEMA public TO {migrator}"))
        database_name = connection.dialect.identifier_preparer.quote(admin_url.database)
        connection.execute(text(f"GRANT CREATE ON DATABASE {database_name} TO {migrator}"))

    migration_url = admin_url.set(username=migrator, password=password)
    monkeypatch.setenv("PENTEST_AGENT_MIGRATION_URL", migration_url.render_as_string(hide_password=False))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    runtime = create_engine(admin_url.set(username=login, password=password), pool_size=1, max_overflow=2)
    try:
        with pytest.raises(RuntimeError, match="Provision pentest_agent_runtime"):
            command.upgrade(config, "head")
        with admin.begin() as connection:
            connection.execute(text("CREATE ROLE pentest_agent_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS"))
            connection.execute(text(f"GRANT pentest_agent_runtime TO {login}"))
        command.upgrade(config, "head")
        yield admin, runtime
        command.downgrade(config, "base")
        with admin.connect() as connection:
            assert connection.scalar(text("SELECT to_regnamespace('pentest_agent')")) is None
        command.upgrade(config, "head")
    finally:
        runtime.dispose()
        admin.dispose()


def seed(admin):
    org_a, org_b, user_a, user_b, customer_a, customer_b, project_a, project_b, restricted = (
        uuid4() for _ in range(9)
    )
    rows = [
        ("organization (id, slug)", "(:id, :slug)", [
            {"id": org_a, "slug": "org-a"}, {"id": org_b, "slug": "org-b"},
        ]),
        ("identity (id, issuer, subject)", "(:id, 'issuer', :subject)", [
            {"id": user_a, "subject": "user-a"}, {"id": user_b, "subject": "user-b"},
        ]),
        ("role (id)", "(:role)", [{"role": "legacy"}]),
        ("organization_membership (org_id, user_id, role_id)", "(:org, :user, 'operator')", [
            {"org": org_a, "user": user_a}, {"org": org_b, "user": user_b},
        ]),
        ("customer (org_id, id, slug, name)", "(:org, :id, :slug, :slug)", [
            {"org": org_a, "id": customer_a, "slug": "customer-a"},
            {"org": org_b, "id": customer_b, "slug": "customer-b"},
        ]),
        ("project (org_id, id, customer_id, slug, environment)", "(:org, :id, :customer, :slug, 'lab')", [
            {"org": org_a, "id": project_a, "customer": customer_a, "slug": "project-a"},
            {"org": org_b, "id": project_b, "customer": customer_b, "slug": "project-b"},
            {"org": org_a, "id": restricted, "customer": customer_a, "slug": "restricted"},
        ]),
        ("project_membership (org_id, project_id, user_id, role_id)", "(:org, :project, :user, 'operator')", [
            {"org": org_a, "project": project_a, "user": user_a},
            {"org": org_b, "project": project_b, "user": user_b},
        ]),
    ]
    with admin.begin() as connection:
        for columns, values, parameters in rows:
            connection.execute(text(f"INSERT INTO pentest_agent.{columns} VALUES {values}"), parameters)
        create_target(connection, org_a, project_a, "a")
        create_target(connection, org_b, project_b, "b")
        create_target(connection, org_a, restricted, "restricted")

    with pytest.raises(DBAPIError) as rejected:
        with admin.begin() as connection:
            create_target(connection, org_a, project_b, "invalid-project-reference")
    assert rejected.value.orig.sqlstate == "23503"
    return org_a, org_b, user_a, user_b, project_a, project_b, restricted


@pytest.fixture(scope="module")
def membership(database):
    return seed(database[0])


def test_runtime_isolation_survives_commits_rollbacks_and_pool_reuse(database, membership):
    _, runtime = database
    org_a, org_b, user_a, user_b, project_a, project_b, restricted = membership
    context_a = {"org_id": org_a, "user_id": user_a, "project_id": project_a}
    context_b = {"org_id": org_b, "user_id": user_b, "project_id": project_b}

    with tenant_transaction(runtime, **context_a) as connection:
        backend = connection.scalar(text("SELECT pg_backend_pid()"))
        assert connection.scalars(TARGETS).all() == ["a"]
        assert connection.execute(text("""
            UPDATE pentest_agent.target SET slug = 'rewritten' WHERE slug = 'b'
        """)).rowcount == 0
        assert connection.execute(text("DELETE FROM pentest_agent.target WHERE slug = 'restricted'")).rowcount == 0
        create_target(connection, org_a, project_a, "new-a")

    for org, project in [(org_b, project_b), (org_a, restricted)]:
        with pytest.raises(DBAPIError) as rejected:
            with tenant_transaction(runtime, **context_a) as connection:
                create_target(connection, org, project, "forbidden")
        assert rejected.value.orig.sqlstate == "42501"

    with pytest.raises(DBAPIError) as moved:
        with tenant_transaction(runtime, **context_a) as connection:
            connection.execute(text("""
                UPDATE pentest_agent.target SET org_id = :org, project_id = :project WHERE slug = 'a'
            """), {"org": org_b, "project": project_b})
    assert moved.value.orig.sqlstate == "42501"

    for denied_context in [
        {**context_a, "project_id": restricted},
        {**context_b, "user_id": user_a},
        {**context_b, "project_id": None},
    ]:
        with tenant_transaction(runtime, **denied_context) as connection:
            assert connection.scalars(TARGETS).all() == []

    with tenant_transaction(runtime, **context_b) as connection:
        assert connection.scalar(text("SELECT pg_backend_pid()")) == backend
        assert connection.scalars(TARGETS).all() == ["b"]

    with runtime.connect() as connection:
        assert connection.scalar(text("SELECT pg_backend_pid()")) == backend
        assert connection.scalars(TARGETS).all() == []
        assert connection.scalars(text("SELECT id FROM pentest_agent.identity")).all() == []

    with pytest.raises(DBAPIError) as no_context:
        with runtime.begin() as connection:
            create_target(connection, org_a, project_a, "no-context")
    assert no_context.value.orig.sqlstate == "42501"

    with tenant_transaction(runtime, **context_a) as connection:
        assert connection.scalars(TARGETS).all() == ["a", "new-a"]


class FixtureProvider:
    active = True

    def authorization_url(self, state, attempt):
        assert attempt.nonce and attempt.verifier
        return f"https://idp.example/authorize?state={state}"

    def exchange(self, code, attempt):
        assert code == "valid-code"
        return Identity("issuer", "user-a")

    def introspect(self, token):
        assert token == "cli-credential"
        if not self.active:
            raise AccessError(401, "invalid_token")
        return Identity("issuer", "user-a")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_api_sessions_csrf_revocation_and_live_memberships(database, membership, anyio_backend):
    admin, runtime = database
    org, foreign_org, user, _, project, foreign_project, _ = membership
    origin = "https://app.example"
    provider = FixtureProvider()
    store = PostgresAuthStore(runtime)
    store.verify_runtime_role()
    with pytest.raises(RuntimeError, match="non-owner"):
        PostgresAuthStore(admin).verify_runtime_role()
    api = build_app(RequestAuth(Authentication(provider, store), origin), store)
    transport = httpx.ASGITransport(app=api)

    async def callback_url(client):
        login = await client.get("/api/v1/auth/login")
        assert login.status_code == 303
        assert {"HttpOnly", "Secure", "SameSite=lax"} <= set(login.headers["set-cookie"].split("; "))
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        return f"/api/v1/auth/callback?code=valid-code&state={state}"

    me = "/api/v1/me"
    project_me = f"{me}?org_id={org}&project_id={project}"
    async with (
        httpx.AsyncClient(transport=transport, base_url=origin, follow_redirects=False) as browser,
        httpx.AsyncClient(transport=transport, base_url=origin, follow_redirects=False) as cli,
    ):
        assert (await browser.get(me)).status_code == 401

        callback = await callback_url(browser)
        login_cookie = browser.cookies[LOGIN_COOKIE]
        assert (await cli.get(callback)).status_code == 401
        response = await browser.get(callback)
        assert response.status_code == 303
        assert response.headers["location"] == f"{origin}/"
        assert response.headers["cache-control"] == "no-store"
        with runtime.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM pentest_agent.web_session")) == 0
        assert (await cli.get(callback, headers={"Cookie": f"{LOGIN_COOKIE}={login_cookie}"})).status_code == 401

        first_token = browser.cookies[SESSION_COOKIE]
        first_csrf = (await browser.get(project_me)).json()["csrf_token"]
        assert (await browser.get(f"{me}?org_id={foreign_org}&project_id={foreign_project}")).status_code == 404
        callback = await callback_url(browser)
        assert (await browser.get(callback)).status_code == 303
        token = browser.cookies[SESSION_COOKIE]
        csrf = (await browser.get(me)).json()["csrf_token"]
        assert token != first_token and csrf != first_csrf
        assert (await cli.get(me, headers={"Cookie": f"{SESSION_COOKIE}={first_token}"})).status_code == 401

        logout = "/api/v1/auth/logout"
        for headers in (
            {},
            {"Origin": "https://other.example", "X-CSRF-Token": csrf},
            {"Origin": origin, "X-CSRF-Token": first_csrf},
        ):
            assert (await browser.post(logout, headers=headers)).status_code == 403
        auth_header = {"Authorization": "Bearer cli-credential"}
        assert (await browser.get(me, headers=auth_header)).status_code == 401
        assert (await browser.post(logout, headers={"Origin": origin, "X-CSRF-Token": csrf})).status_code == 204
        assert (await cli.get(me, headers={"Cookie": f"{SESSION_COOKIE}={token}"})).status_code == 401

        callback = await callback_url(browser)
        assert (await browser.get(callback)).status_code == 303
        with admin.begin() as connection:
            connection.execute(text("UPDATE pentest_agent.web_session SET expires_at = now()"))
        assert (await browser.get(me)).status_code == 401

        assert (await cli.get(project_me, headers=auth_header)).json()["project_role"] == "operator"
        for role, expected in (("viewer", 200), ("legacy", 403)):
            with admin.begin() as connection:
                connection.execute(text("""
                    UPDATE pentest_agent.project_membership SET role_id = :role
                    WHERE org_id = :org AND project_id = :project AND user_id = :user
                """), {"role": role, "org": org, "project": project, "user": user})
            assert (await cli.get(project_me, headers=auth_header)).status_code == expected
            if role == "viewer":
                with pytest.raises(AccessError) as denied:
                    with store.project(user, org, project, Action.MANAGE_TARGETS):
                        pytest.fail("Viewer must not manage targets")
                assert denied.value.status == 403

        with admin.begin() as connection:
            connection.execute(text("""
                DELETE FROM pentest_agent.project_membership
                WHERE org_id = :org AND project_id = :project AND user_id = :user
            """), {"org": org, "project": project, "user": user})
        assert (await cli.get(project_me, headers=auth_header)).status_code == 404
        provider.active = False
        assert (await cli.get(me, headers=auth_header)).status_code == 401


class EngagementProvider(FixtureProvider):
    def introspect(self, token):
        return Identity("issuer", f"engagement-{token}")


class AnalysisProvider:
    model = ModelVersion(id="postgres-fixture", digest="a" * 64)

    def __init__(self, store):
        self.store = store
        self.calls = 0
        self.during_call = None
        self.body = b'{"kind":"abstain"}'

    def complete(self, instructions, context, **limits):
        assert self.store.engine.pool.checkedout() == 0
        assert "plan_id" not in context.decode()
        assert "evidence" in json.loads(context)
        assert limits["output_token_limit"] == 192
        self.calls += 1
        if self.during_call:
            self.during_call()
        return ProviderReply(body=self.body, input_tokens=100, output_tokens=10)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_inventory_and_immutable_authorization_workflow(database, membership, anyio_backend):
    admin, runtime = database
    other_org, _, _, _, other_project, _, _ = membership
    roles = ["platform", "admin", "operator", "approver", "viewer"]
    users = {role: uuid4() for role in roles}
    with admin.begin() as connection:
        for role, user in users.items():
            connection.execute(text("""
                INSERT INTO pentest_agent.identity (id, issuer, subject) VALUES (:id, 'issuer', :subject)
            """), {"id": user, "subject": f"engagement-{role}"})
        connection.execute(text("INSERT INTO pentest_agent.platform_admin (user_id) VALUES (:id)"),
                           {"id": users["platform"]})

    origin = "https://app.example"
    store = PostgresAuthStore(runtime)
    access = RequestAuth(Authentication(EngagementProvider(), store), origin)
    cipher = DocumentCipher(b64encode(b"x" * 32).decode())
    inference = AnalysisProvider(store)
    api = build_app(access, store, cipher=cipher, inference=(inference.model, inference))
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        async def call(method, path, role, status, *, org=None, json=None, data=None, headers=None, query=None):
            combined = {"Authorization": f"Bearer {role}", **(headers or {})}
            params = {"org_id": str(org)} if org else {}
            params.update(query or {})
            response = await client.request(method, f"/api/v1{path}", params=params, headers=combined,
                                            json=json, content=data)
            expected = status if isinstance(status, tuple) else (status,)
            assert response.status_code in expected, response.text
            return response

        provision = {"slug": "engagement-org", "admin_id": str(users["admin"])}
        await call("POST", "/organizations", "admin", 403, json=provision)
        org = (await call("POST", "/organizations", "platform", 201, json=provision)).json()["id"]
        with pytest.raises(DBAPIError) as membership_denied:
            with tenant_transaction(runtime, org_id=org, user_id=users["platform"]) as connection:
                connection.execute(text("""
                    INSERT INTO pentest_agent.organization_membership (org_id, user_id, role_id)
                    VALUES (:org, :user, 'org_admin')
                """), {"org": org, "user": users["viewer"]})
        assert membership_denied.value.orig.sqlstate == "42501"
        assert (await call("GET", "/organizations", "platform", 200)).json()["items"] == []
        assert (await call("GET", "/organizations", "admin", 200)).json()["items"][0]["id"] == org
        await call("GET", f"/organizations/{org}", "platform", 404)
        await call("PATCH", f"/organizations/{org}", "admin", 200, headers={"If-Match": '"1"'},
                   json={"slug": "renamed-org"})

        customer = (await call("POST", "/customers", "admin", 201, org=org,
                               json={"slug": "client", "name": "Customer"})).json()["id"]
        await call("PATCH", f"/customers/{customer}", "admin", 428, org=org, json={"name": "New name"})
        await call("PATCH", f"/customers/{customer}", "admin", 200, org=org, headers={"If-Match": '"1"'},
                   json={"name": "New name"})
        await call("PATCH", f"/customers/{customer}", "admin", 412, org=org, headers={"If-Match": '"1"'},
                   json={"name": "Stale name"})
        project = (await call("POST", "/projects", "admin", 201, org=org,
                              json={"slug": "project", "customer_id": customer, "environment": "lab"})).json()["id"]
        await call("DELETE", f"/customers/{customer}", "admin", 409, org=org, headers={"If-Match": '"2"'})
        second_project = (await call(
            "POST", "/projects", "admin", 201, org=org,
            json={"slug": "second-project", "customer_id": customer, "environment": "lab"},
        )).json()["id"]
        with pytest.raises(DBAPIError) as membership_denied:
            with tenant_transaction(runtime, org_id=org, project_id=second_project, user_id=users["admin"]) as connection:
                connection.execute(text("""
                    INSERT INTO pentest_agent.project_membership (org_id, project_id, user_id, role_id)
                    VALUES (:org, :project, :user, 'project_admin')
                """), {"org": org, "project": second_project, "user": users["admin"]})
        assert membership_denied.value.orig.sqlstate == "42501"
        path = f"/projects/{project}"
        assert (await call("GET", "/ready", "admin", 200)).json()["status"] == "ready"
        with admin.begin() as connection:
            connection.execute(text("UPDATE public.pentest_agent_alembic_version SET version_num = '0004_scope_review'"))
        try:
            stale = await call("GET", "/ready", "admin", 503)
            assert stale.json()["code"] == "schema_not_ready"
        finally:
            with admin.begin() as connection:
                connection.execute(text("UPDATE public.pentest_agent_alembic_version SET version_num = :revision"),
                                   {"revision": SCHEMA_REVISION})
        project_list = (await call("GET", "/projects", "admin", 200, org=org)).json()["items"]
        assert {item["id"] for item in project_list} == {project, second_project}
        first_page = (await call("GET", "/projects", "admin", 200, org=org, query={"limit": 1})).json()
        assert first_page["next_cursor"] == first_page["items"][0]["id"]
        final_page = (await call("GET", "/projects", "admin", 200, org=org,
                                 query={"limit": 1, "after": first_page["next_cursor"]})).json()
        assert final_page["next_cursor"] is None
        assert {first_page["items"][0]["id"], final_page["items"][0]["id"]} == {project, second_project}
        await call("GET", path, "admin", 404, org=other_org)
        await call("GET", f"/projects/{other_project}", "admin", 404, org=org)

        with admin.begin() as connection:
            for role in ("operator", "approver", "viewer"):
                arguments = {"org": org, "project": project, "user": users[role], "role": role}
                connection.execute(text("""
                    INSERT INTO pentest_agent.organization_membership (org_id, user_id, role_id)
                    VALUES (:org, :user, :role)
                """), arguments)
                connection.execute(text("""
                    INSERT INTO pentest_agent.project_membership (org_id, project_id, user_id, role_id)
                    VALUES (:org, :project, :user, :role)
                """), arguments)

            connection.execute(text("""
                INSERT INTO pentest_agent.project_membership (org_id, project_id, user_id, role_id)
                VALUES (:org, :project, :user, 'operator')
            """), {"org": org, "project": second_project, "user": users["operator"]})

        old = b'{"url":"https://old.example","findings":[{"type":"info","detail":"old evidence"}]}'
        import_headers = {"Content-Type": "application/octet-stream"}
        imports = path + "/legacy-imports"
        docs = path + "/authorization-documents"
        pdf_headers = {"Content-Type": "application/pdf"}
        pdf_payload = b"%PDF-1.4\nPrivate signed authorization sample\n%%EOF"
        await check_upload_admission(call, admin, runtime, org, other_org, project, users["operator"], (
            (imports, import_headers, {"format": "json"}, old),
            (docs, pdf_headers, {}, pdf_payload),
        ))
        await call("POST", imports, "viewer", 403, org=org, query={"format": "json"}, headers=import_headers, data=old)
        await call("POST", imports, "operator", 422, org=org, query={"format": "json"}, headers=import_headers, data=b"!")
        imported = (await call("POST", imports, "operator", 201, org=org, query={"format": "json"},
                               headers=import_headers, data=old)).json()
        repeated = (await call("POST", imports, "operator", 201, org=org, query={"format": "json"},
                               headers=import_headers, data=old)).json()
        assert imported["id"] == repeated["id"] and repeated["duplicate"] and imported["finding_count"] == 1
        imported_path = imports + f"/{imported['id']}"
        imported_record = (await call("GET", imported_path, "viewer", 200, org=org)).json()["findings"][0]
        assert imported_record["confidence"] == "unverified" and imported_record["observed_url"] is None
        await call("GET", f"/projects/{second_project}/legacy-imports/{imported['id']}", "operator", 404, org=org)

        target = {"slug": "asset", "environment": "lab", "address": "https://EXAMPLE.net:443/api/",
                  "attribution": "first_party"}
        await call("POST", path + "/targets", "viewer", 403, org=org, json=target)
        payload = (await call("POST", path + "/targets", "operator", 201, org=org, json=target)).json()
        assert payload["canonical_address"] == "https://example.net/api/"
        target_path = path + f"/targets/{payload['id']}"
        await call("PATCH", target_path, "operator", 200, org=org, headers={"If-Match": '"1"'},
                   json={"slug": "asset-updated"})
        await call("DELETE", target_path, "operator", 204, org=org, headers={"If-Match": '"2"'})
        await call("GET", target_path, "viewer", 404, org=org)

        await call("POST", docs, "operator", 415, org=org, data=pdf_payload)
        await call("POST", docs, "operator", 413, org=org, headers=pdf_headers,
                   data=b"%PDF-" + b"x" * MAX_DOCUMENT_SIZE)
        assert (await call("POST", docs, "operator", 422, org=org, headers=pdf_headers,
                           data=b"not a PDF")).json()["code"] == "invalid_document"
        uploaded = (await call("POST", docs, "operator", 201, org=org, headers=pdf_headers, data=pdf_payload)).json()
        digest = sha256(pdf_payload).hexdigest()
        assert uploaded["digest"] == digest
        with admin.connect() as connection:
            ciphertext = connection.scalar(text("SELECT ciphertext FROM pentest_agent.authorization_document"))
            assert pdf_payload not in ciphertext
        download = docs + f"/{uploaded['id']}"
        await call("GET", download, "viewer", 404, org=org)
        await call("GET", download, "platform", 404, org=org)
        downloaded = await call("GET", download, "approver", 200, org=org)
        assert downloaded.content == pdf_payload
        assert downloaded.headers["content-disposition"].startswith("attachment;")
        assert downloaded.headers["cache-control"] == "no-store"

        records = path + "/authorizations"
        now = datetime.now(timezone.utc)
        body = {"document_evidence_id": uploaded["id"], "delegator_id": str(users["admin"]),
                "valid_from": (now - timedelta(minutes=1)).isoformat(),
                "valid_until": (now + timedelta(hours=1)).isoformat(),
                "scope_rules": [{"kind": "fqdn", "destination": "Example.net", "effect": "allow"}], "limits": {}}
        await call("POST", records, "operator", 422, org=org, json={**body, "valid_until": body["valid_from"]})
        await call("POST", records, "operator", 404, org=org, json={**body, "document_evidence_id": str(uuid4())})
        await call("POST", f"/projects/{second_project}/authorizations", "operator", 404, org=org, json=body)
        initial = (await call("POST", records, "operator", 201, org=org, json=body)).json()
        assert initial["document_digest"] == digest and initial["status"] == "draft"
        assert initial["scope_rules"][0]["destination"] == "example.net"
        record = records + f"/{initial['id']}"
        decision = {"revision": 1, "decision": "approve", "reason": "Document reviewed"}
        await call("POST", record + "/decisions", "operator", 403, org=org, json=decision)
        with admin.begin() as connection:
            connection.execute(text("""
                UPDATE pentest_agent.project_membership SET role_id = 'approver'
                WHERE org_id = :org AND project_id = :project AND user_id = :user
            """), {"org": org, "project": project, "user": users["operator"]})
        result = await call("POST", record + "/decisions", "operator", 403, org=org, json=decision)
        assert result.json()["code"] == "approval_requires_distinct_actor"
        with admin.begin() as connection:
            connection.execute(text("""
                UPDATE pentest_agent.project_membership SET role_id = 'operator'
                WHERE org_id = :org AND project_id = :project AND user_id = :user
            """), {"org": org, "project": project, "user": users["operator"]})
        approved = (await call("POST", record + "/decisions", "approver", 200, org=org, json=decision)).json()
        assert approved["effective_status"] == "active" and approved["verifier_id"] == str(users["approver"])
        plan_path = await check_scope_reviews(call, admin, org, project, path, target, initial["id"])
        saved_plan = (await call("GET", plan_path, "viewer", 200, org=org)).json()
        saved_report = (await call("GET", plan_path + "/report", "viewer", 200, org=org)).content
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.downgrade(config, "0006_pilot_memberships")
        stale_schema = await call("GET", "/ready", "admin", 503)
        assert stale_schema.json()["code"] == "schema_not_ready"
        command.upgrade(config, "head")
        await call("GET", "/ready", "admin", 200)

        catalog = (await call("GET", path + "/team-modes", "viewer", 200, org=org)).json()["items"]
        assert len(catalog) == 10
        assert {item["manifest"]["id"] for item in catalog if item["eligible_for_analysis"]} == {"white", "blue", "purple"}
        digests = {item["manifest"]["id"]: item["digest"] for item in catalog}
        selection = path + "/team-selection"
        empty = await call("GET", selection, "viewer", 200, org=org)
        assert empty.json() == {"version": 0, "selection": None} and empty.headers["etag"] == '"0"'
        await call("PUT", selection, "admin", 428, org=org, json={"mode_id": "red"})
        await call("PUT", selection, "operator", 403, org=org, headers={"If-Match": '"0"'}, json={"mode_id": "red"})
        await call("GET", selection, "admin", 404, org=other_org)

        selected = await call("PUT", selection, "admin", 200, org=org,
                              headers={"If-Match": '"0"'}, json={"mode_id": "red"})
        assert selected.headers["etag"] == '"1"'
        assert selected.json()["selection"]["mode_digest"] == digests["red"]
        assert selected.json()["selection"]["actor_id"] == str(users["admin"])
        assert (await call("GET", selection, "viewer", 200, org=org)).json() == selected.json()

        concurrent = await asyncio.gather(*[
            client.put(f"/api/v1{selection}", params={"org_id": org}, json={"mode_id": mode},
                       headers={"Authorization": "Bearer admin", "If-Match": '"1"'})
            for mode in ("rainbow", "blue")
        ])
        assert sorted(response.status_code for response in concurrent) == [200, 412]
        latest_selection = (await call("GET", selection, "viewer", 200, org=org)).json()
        assert latest_selection["version"] == 2
        assert latest_selection["selection"]["mode_id"] in {"rainbow", "blue"}
        second_selection = f"/projects/{second_project}/team-selection"
        assert (await call("GET", second_selection, "operator", 200, org=org)).json()["selection"] is None
        await call("PUT", second_selection, "admin", 200, org=org,
                   headers={"If-Match": '"0"'}, json={"mode_id": "gold"})
        assert (await call("GET", selection, "viewer", 200, org=org)).json() == latest_selection

        with tenant_transaction(runtime, org_id=org, project_id=project, user_id=users["viewer"]) as connection:
            rows = connection.execute(text("""
                SELECT project_id, version FROM pentest_agent.project_team_selection ORDER BY version
            """)).all()
            assert [(str(project_id), version) for project_id, version in rows] == [(project, 1), (project, 2)]
        with pytest.raises(DBAPIError) as denied:
            with tenant_transaction(runtime, org_id=org, project_id=project, user_id=users["operator"]) as connection:
                connection.execute(text("""
                    INSERT INTO pentest_agent.project_team_selection
                        (org_id, project_id, version, mode_id, mode_version, mode_digest, actor_id)
                    VALUES (:org, :project, 3, 'red', 1, :digest, :actor)
                """), {"org": org, "project": project, "digest": digests["red"], "actor": users["operator"]})
        assert denied.value.orig.sqlstate == "42501"
        assert (await call("GET", plan_path, "viewer", 200, org=org)).json() == saved_plan
        assert (await call("GET", plan_path + "/report", "viewer", 200, org=org)).content == saved_report
        assert (await call("POST", plan_path + "/verify", "viewer", 200, org=org,
                           json={"hash": saved_plan["hash"]})).json()["execution"] == "disabled"
        await check_organization_stop(call, admin, runtime, org, other_org, users, plan_path, saved_plan)
        dispatch, mandate_id, work = await check_evidence_permissions(
            call, admin, store, cipher, org, other_org, project, users, path, saved_plan,
            imported["id"], sha256(old).hexdigest(), inference,
        )
        proposal = generate_proposal(work.prepared, inference.model, inference)

        await call("POST", record + "/decisions", "approver", 409, org=org, json=decision)
        await call("POST", record + "/revisions", "operator", 409, org=org, json={**body, "previous_revision": 1})

        await call("POST", record + "/decisions", "approver", 200, org=org,
                   json={**decision, "decision": "revoke", "reason": "Mandate changed"})
        receipt = dispatch.finish(mandate_id, "white", "lifecycle-stale-mandate", work.reservation_id,
                                  output=StepOutput(status="inconclusive"), failure=None, proposal=proposal)
        assert receipt["state"] == "blocked" and receipt["reason"] == "plan_state_changed"
        assert_private_analysis_result(admin, mandate_id, None, None)
        plan = (await call("GET", plan_path, "viewer", 200, org=org)).json()
        assert plan == saved_plan and plan["status"] == "reviewed"
        report = await call("GET", plan_path + "/report", "viewer", 200, org=org)
        assert report.headers["content-type"].startswith("text/html")
        assert plan["hash"] in report.text and "Ejecución deshabilitada" in report.text
        assert report.headers["content-disposition"].endswith(f'{plan["id"]}.html"')
        assert report.content == saved_report
        await call("GET", plan_path + "/report", "viewer", 404, org=other_org)
        stale = await call("POST", plan_path + "/verify", "operator", 409, org=org, json={"hash": plan["hash"]})
        assert stale.json()["code"] == "plan_state_changed"
        blocked_body = {"assessment_id": plan["assessment_id"], "authorization_id": initial["id"],
                        "authorization_revision": 1, "target_ids": [item["id"] for item in plan["targets"]]}
        blocked = (await call("POST", path + "/plans", "operator", 201, org=org, json=blocked_body,
                              headers={"Idempotency-Key": "review-revoked-0001"})).json()
        assert blocked["status"] == "blocked" and blocked["denials"] == ["revoked"]
        blocked_path = path + f"/plans/{blocked['id']}/verify"
        failure = await call("POST", blocked_path, "viewer", 409, org=org, json={"hash": blocked["hash"]})
        assert failure.json()["code"] == "plan_blocked"
        latest = (await call("POST", record + "/revisions", "operator", 201, org=org,
                             json={**body, "previous_revision": 1})).json()
        assert latest["revision"] == 2 and latest["status"] == "draft"
        historical = (await call("GET", record, "viewer", 200, org=org, query={"revision": 1})).json()
        assert historical["status"] == "revoked" and historical["document_digest"] == digest
        assert historical["approval_reason"] == "Document reviewed"
        active = (await call("GET", records, "viewer", 200, org=org)).json()["items"]
        assert [item["revision"] for item in active] == [2]

        await call("DELETE", path, "admin", 204, org=org, headers={"If-Match": '"1"'})
        await call("GET", selection, "viewer", 200, org=org)
        await call("PUT", selection, "admin", 409, org=org, headers={"If-Match": '"2"'}, json={"mode_id": "gold"})
        await call("POST", path + "/targets", "operator", 409, org=org, json=target)
        await call("GET", record, "viewer", 200, org=org)


async def check_organization_stop(call, admin, runtime, org, other_org, users, plan_path, plan):
    org_path = f"/organizations/{org}"
    stop = org_path + "/stop"
    initial = (await call("GET", org_path, "admin", 200)).json()
    before = await call("GET", stop, "admin", 200)
    assert before.json() == {"enabled": False, "revision": 0} and before.headers["etag"] == '"0"'
    await call("GET", f"/organizations/{other_org}/stop", "admin", 404)
    await call("PUT", stop, "operator", 403, headers={"If-Match": '"0"'}, json={"enabled": True, "reason": "Denied"})
    await call("PUT", stop, "admin", 428, json={"enabled": True, "reason": "Stop requested"})
    await call("PUT", stop, "admin", 422, headers={"If-Match": '"0"'}, json={"enabled": True, "reason": " "})
    with pytest.raises(DBAPIError) as denied:
        with tenant_transaction(runtime, org_id=UUID(org), user_id=users["admin"]) as connection:
            connection.execute(text("UPDATE pentest_agent.organization SET kill_switch = true WHERE id = :id"), {"id": org})
    assert denied.value.orig.sqlstate == "42501"

    outcomes = await asyncio.gather(*[
        call("PUT", stop, "admin", (200, 412), headers={"If-Match": '"0"'},
             json={"enabled": True, "reason": "Pause exercises"})
        for _ in range(2)
    ])
    assert sorted(response.status_code for response in outcomes) == [200, 412]
    assert (await call("GET", stop, "admin", 200)).json() == {"enabled": True, "revision": 1}
    blocked = await call("POST", plan_path + "/verify", "operator", 409, org=org, json={"hash": plan["hash"]})
    assert blocked.json()["code"] == "plan_state_changed"
    assert (await call("GET", plan_path, "viewer", 200, org=org)).json() == plan

    resumed = await call("PUT", stop, "admin", 200, headers={"If-Match": '"1"'},
                         json={"enabled": False, "reason": "Review complete"})
    assert resumed.json() == {"enabled": False, "revision": 2} and resumed.headers["etag"] == '"2"'
    assert (await call("GET", org_path, "admin", 200)).json() == initial
    await call("POST", plan_path + "/verify", "operator", 200, org=org, json={"hash": plan["hash"]})
    with admin.connect() as connection:
        journal = connection.execute(text("""
            SELECT revision, enabled, actor_id, reason FROM pentest_agent.organization_stop_event
            WHERE org_id = :org ORDER BY revision
        """), {"org": org}).all()
    assert journal == [(1, True, users["admin"], "Pause exercises"), (2, False, users["admin"], "Review complete")]


async def check_evidence_permissions(call, admin, store, cipher, org, other_org, project, users, path, plan,
                                     legacy_id, legacy_digest, inference):
    target = plan["targets"][0]["id"]
    payload = json.dumps({"target_id": target, "observations": [{"control": "logging", "result": "observed"}]}).encode()
    digest = sha256(payload).hexdigest()
    withdrawn_payload = payload.replace(b'"observed"', b'"missing"')
    withdrawn_digest = sha256(withdrawn_payload).hexdigest()
    source = {"kind": "control-observations-v1", "target_id": target, "digest": digest,
              "size_bytes": len(payload), "classification": "internal", "capability": "capture-review"}
    removable_source = {**source, "digest": withdrawn_digest, "size_bytes": len(withdrawn_payload)}
    legacy = {**source, "kind": "legacy-reference-v1", "digest": legacy_digest,
              "size_bytes": None, "legacy_id": legacy_id}
    mode = TEAM_CATALOG[TeamId.RED]
    import_scope = plan["authorization"]
    spec = {"plan_id": plan["id"], "plan_hash": plan["hash"], "mode_id": mode.id.value,
            "mode_version": mode.version, "mode_digest": mode.digest, "valid_from": import_scope["valid_from"],
            "valid_until": import_scope["valid_until"], "sources": [source, legacy, removable_source]}
    root = path + "/evidence-permissions"
    creation_key = {"Idempotency-Key": "scope-evidence-first-request"}
    await call("POST", root, "viewer", 403, org=org, headers=creation_key, json=spec)
    initial = (await call("POST", root, "operator", 201, org=org, headers=creation_key, json=spec)).json()
    assert (await call("POST", root, "operator", 201, org=org, headers=creation_key, json=spec)).json() == initial
    await call("POST", root, "operator", 409, org=org, headers=creation_key, json={**spec, "sources": [source]})
    permission = root + "/" + initial["id"]
    await call("GET", permission, "viewer", 404, org=org)
    await call("GET", permission, "approver", 404, org=other_org)
    assert (await call("GET", permission, "approver", 200, org=org)).json()["status"] == "pending"

    upload_path = permission + "/revisions/1/sources/" + digest
    content_type = {"Content-Type": "application/json"}

    async def unexpected_body():
        pytest.fail("Read evidence before checking its permission")
        yield payload

    await call("PUT", upload_path, "operator", 409, org=org, headers=content_type, data=unexpected_body())
    await call("PUT", upload_path, "operator", 404, org=other_org, headers=content_type, data=unexpected_body())
    approval = {"revision": 1, "decision": "approve", "reason": "Source and asset verified"}
    await call("POST", permission + "/decisions", "operator", 403, org=org, json=approval)
    approved = (await call("POST", permission + "/decisions", "approver", 200, org=org, json=approval)).json()
    assert approved["status"] == "approved" and approved["approver_id"] == str(users["approver"])
    await call("PUT", upload_path, "operator", 413, org=org, headers=content_type, data=payload + b" ")
    await call("PUT", upload_path, "operator", 422, org=org, headers=content_type, data=payload[:-1])
    receipts = await asyncio.gather(*[
        call("PUT", upload_path, "operator", 200, org=org, headers=content_type, data=payload)
        for _ in range(2)
    ])
    assert receipts[0].json() == receipts[1].json()
    assert receipts[0].json()["source_digest"] == digest

    ids = (UUID(org), UUID(project), UUID(initial["id"]))
    with store.project(users["operator"], *ids[:2], Action.READ) as (connection, caller):
        projected = analysis_context(connection, caller, cipher, ids[2], 1, digest)
        assert projected["source"] == json.loads(payload)
        assert "canonical_address" not in projected["scope"] and "authorization" not in projected["scope"]
        old = analysis_context(connection, caller, cipher, ids[2], 1, legacy_digest)
        assert old["source"] == {"id": legacy_id, "target_id": target, "origin": "legacy",
                                 "confidence": "unverified", "finding_count": 1}
        encrypted = connection.execute(text("SELECT ciphertext FROM pentest_agent.evidence_projection")).scalar_one()
        assert b"logging" not in encrypted
    with store.project(users["approver"], *ids[:2], Action.READ) as (connection, caller):
        assert analysis_context(connection, caller, cipher, ids[2], 1, digest) == projected
    with store.project(users["viewer"], *ids[:2], Action.READ) as (connection, caller):
        assert connection.scalar(text("SELECT count(*) FROM pentest_agent.evidence_projection")) == 0
        with pytest.raises(AccessError, match="evidence_permission_not_found"):
            analysis_context(connection, caller, cipher, ids[2], 1, digest)

    await check_analysis_publication(call, admin, store, cipher, org, project, users, path, spec,
                                     {**source, "capability": "scope-record-review"}, payload, inference)
    mandate_probe = await check_analysis_ledger(call, admin, store, cipher, org, project, users, path, spec, legacy, inference)

    legacy_disposition = permission + "/revisions/1/sources/" + legacy_digest + "/disposition"
    await call("PUT", legacy_disposition, "operator", 403, org=org, json={"reason": "Remove historic reference"})
    receipt = (await call("PUT", legacy_disposition, "approver", 200, org=org,
                          json={"reason": "Remove historic reference"})).json()
    assert receipt["kind"] == "withdrawn" and receipt["actor_id"] == str(users["approver"])
    assert (await call("GET", legacy_disposition, "operator", 200, org=org)).json() == receipt
    with store.project(users["operator"], *ids[:2], Action.READ) as (connection, caller):
        with pytest.raises(AccessError, match="evidence_disposed"):
            analysis_context(connection, caller, cipher, ids[2], 1, legacy_digest)

    removable_path = permission + "/revisions/1/sources/" + withdrawn_digest
    await call("PUT", removable_path, "operator", 200, org=org, headers=content_type, data=withdrawn_payload)
    removed = (await call("PUT", removable_path + "/disposition", "approver", 200, org=org,
                          json={"reason": "Remove uploaded projection"})).json()
    repeated = (await call("PUT", removable_path + "/disposition", "approver", 200, org=org,
                            json={"reason": "A retry cannot replace the receipt"})).json()
    assert repeated == removed
    await call("PUT", removable_path, "operator", 409, org=org, headers=content_type, data=unexpected_body())
    with store.project(users["operator"], *ids[:2], Action.READ) as (connection, caller):
        assert connection.scalar(text("""
            SELECT count(*) FROM pentest_agent.evidence_projection WHERE source_digest = :digest
        """), {"digest": withdrawn_digest}) == 0
        with pytest.raises(AccessError, match="evidence_disposed"):
            analysis_context(connection, caller, cipher, ids[2], 1, withdrawn_digest)

    revision = (await call("POST", permission + "/revisions", "operator", 201, org=org,
                           headers={"Idempotency-Key": "scope-evidence-second-request"},
                           json={"previous_revision": 1, "spec": spec})).json()
    assert revision["revision"] == 2
    historical = (await call("GET", permission, "operator", 200, org=org, query={"revision": 1})).json()
    assert historical == approved
    await call("PUT", upload_path, "operator", 409, org=org, headers=content_type, data=unexpected_body())

    decisions = permission + "/decisions"
    revoked = {**approval, "revision": 2, "decision": "revoke", "reason": "Scope changed"}
    approval_race, _ = await asyncio.gather(
        call("POST", decisions, "approver", (200, 409), org=org, json={**approval, "revision": 2}),
        call("POST", decisions, "approver", 200, org=org, json=revoked),
    )
    await call("POST", decisions, "approver", 409, org=org, json={**approval, "revision": 2})
    settled = (await call("GET", permission, "operator", 200, org=org)).json()
    assert settled["status"] == "revoked" and settled["revocation_reason"] == revoked["reason"]
    assert bool(settled["approved_at"]) == (approval_race.status_code == 200)

    third = (await call("POST", permission + "/revisions", "operator", 201, org=org,
                        headers={"Idempotency-Key": "scope-evidence-third-request"},
                        json={"previous_revision": 2, "spec": spec})).json()
    assert third["revision"] == 3
    await call("POST", decisions, "approver", 200, org=org, json={**approval, "revision": 3})

    async def revoke_during_upload():
        await call("POST", decisions, "approver", 200, org=org, json={**revoked, "revision": 3})
        yield payload

    await call("PUT", permission + "/revisions/3/sources/" + digest, "operator", 409,
               org=org, headers=content_type, data=revoke_during_upload())

    with admin.begin() as connection:
        projection = connection.execute(text("""
            SELECT * FROM pentest_agent.evidence_projection
            WHERE permission_id = :id AND revision = 1 AND source_digest = :digest
        """), {"id": ids[2], "digest": digest}).mappings().one()
        connection.execute(text("""
            UPDATE pentest_agent.evidence_permission
            SET spec = jsonb_set(spec, '{sources,0,retain_until}', to_jsonb((clock_timestamp() - interval '1 second')))
            WHERE id = :id AND revision = 1
        """), {"id": ids[2]})
        # The two withdrawn publication fixtures are removed with the two original projections.
        assert connection.scalar(text("SELECT pentest_agent.sweep_evidence_retention()")) == 4
        connection.execute(text("""
            INSERT INTO pentest_agent.evidence_projection (
                org_id, project_id, id, permission_id, revision, source_digest, projection_digest, nonce, ciphertext
            ) VALUES (
                :org_id, :project_id, :id, :permission_id, :revision, :source_digest, :projection_digest, :nonce, :ciphertext
            )
        """), dict(projection))
        assert connection.scalar(text("SELECT pentest_agent.sweep_evidence_retention()")) == 1
        assert connection.scalar(text("SELECT pentest_agent.sweep_evidence_retention()")) == 0
    upload_disposition = upload_path + "/disposition"
    expired = (await call("GET", upload_disposition, "operator", 200, org=org)).json()
    assert expired["kind"] == "expired" and expired["reason"] == "retention_elapsed"
    await check_event_batch_upload(call, store, cipher, org, other_org, project, users, root, spec, target)
    await check_sarif_upload(call, org, other_org, root, spec, target)
    return mandate_probe


async def check_sarif_upload(call, org, other_org, root, spec, target):
    fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "yellow-sarif-2.1.0.json"
    payload = fixture.read_bytes()
    digest = sha256(payload).hexdigest()
    provenance = {"producer": "fixture-ci", "producer_version": "1.2.0",
                  "repository_uri": "https://git.example.test/team/service.git", "revision_id": "1" * 40}
    source = {"kind": "sarif-v1", "target_id": target, "capability": "code-review", "classification": "internal",
              "digest": digest, "size_bytes": len(payload), "sarif_provenance": provenance}
    mode = TEAM_CATALOG[TeamId.YELLOW]
    permission_spec = {**spec, "mode_id": mode.id.value, "mode_version": mode.version, "mode_digest": mode.digest,
                       "sources": [source]}
    headers = {"Content-Type": "application/sarif+json"}
    approval = {"revision": 1, "decision": "approve", "reason": "Verified producer, revision and asset"}

    async def request(source_data, key):
        permit = (await call("POST", root, "operator", 201, org=org, headers={"Idempotency-Key": key},
                             json={**permission_spec, "sources": [source_data]})).json()
        return root + "/" + permit["id"]

    mismatched = await request({**source, "sarif_provenance": {**provenance, "revision_id": "2" * 40}},
                               "yellow-sarif-revision-mismatch")
    await call("POST", mismatched + "/decisions", "approver", 200, org=org, json=approval)
    refused = await call("PUT", mismatched + "/revisions/1/sources/" + digest, "operator", 422,
                         org=org, headers=headers, data=payload)
    assert refused.json()["code"] == "evidence_sarif_provenance_mismatch"

    permission = await request(source, "yellow-sarif-custody-request")
    upload = f"{permission}/revisions/1/sources/{digest}"
    await call("PUT", upload, "operator", 409, org=org, headers=headers, data=payload)
    await call("POST", permission + "/decisions", "approver", 200, org=org, json=approval)
    await call("PUT", upload, "operator", 404, org=other_org, headers=headers, data=payload)
    await call("PUT", upload, "operator", 413, org=org, headers=headers, data=payload + b" ")
    stored = (await call("PUT", upload, "operator", 200, org=org, headers=headers, data=payload)).json()
    assert (await call("PUT", upload, "operator", 200, org=org, headers=headers, data=payload)).json() == stored
    projection_path = upload + "/sarif"
    await call("GET", projection_path, "viewer", 404, org=org)
    await call("GET", projection_path, "operator", 404, org=other_org)
    for role in ("operator", "approver"):
        projection = (await call("GET", projection_path, role, 200, org=org)).json()
        assert projection == {"target_id": target, "sarif_version": "2.1.0", "provenance": provenance,
                              "locations": [{"rule_id": "review.config.required", "path": "src/config.py",
                                             "start_line": 12, "end_line": 14}]}
    await call("PUT", upload + "/disposition", "approver", 200, org=org, json={"reason": "Withdraw SARIF evidence"})
    await call("GET", projection_path, "operator", 409, org=org)


async def check_event_batch_upload(call, store, cipher, org, other_org, project, users, path, spec, target):
    event = {"event_id": str(uuid4()), "occurred_at": "2026-01-01T11:00:00-03:00", "kind": "login-failure"}
    batch = {"target_id": target, "producer": "identity-audit", "window_start": "2026-01-01T13:00:00Z",
             "window_end": "2026-01-01T15:00:00Z", "events": [event]}
    payload = json.dumps(batch).encode()
    source = {"kind": "event-batch-v1", "capability": "event-review", "target_id": target,
              "digest": sha256(payload).hexdigest(), "size_bytes": len(payload), "classification": "restricted"}
    mode = TEAM_CATALOG[TeamId.BLUE]
    receipt = (await call("POST", path, "operator", 201, org=org, headers={"Idempotency-Key": "blue-event-batch-request"},
                          json={**spec, "mode_id": mode.id.value, "mode_digest": mode.digest,
                                "mode_version": mode.version, "sources": [source]})).json()
    permission_id = receipt["id"]
    root = f"{path}/{permission_id}"
    upload = f"{root}/revisions/1/sources/{source['digest']}"
    headers = {"Content-Type": "application/json"}
    await call("PUT", upload, "operator", 409, org=org, headers=headers, data=payload)
    await call("POST", root + "/decisions", "approver", 200, org=org,
               json={"revision": 1, "decision": "approve", "reason": "Collector verified"})
    await call("PUT", upload, "operator", 404, org=other_org, headers=headers, data=payload)
    stored = (await call("PUT", upload, "operator", 200, org=org, headers=headers, data=payload)).json()
    assert (await call("PUT", upload, "operator", 200, org=org, headers=headers, data=payload)).json() == stored
    for role in ("operator", "approver"):
        with store.project(users[role], UUID(org), UUID(project), Action.READ) as (connection, caller):
            context = analysis_context(connection, caller, cipher, UUID(permission_id), 1, source["digest"])
            assert context["source"] == {**batch, "events": [{**event, "occurred_at": "2026-01-01T14:00:00Z"}]}

    project_root = path.removesuffix("/evidence-permissions")
    selection = project_root + "/team-selection"
    prior = (await call("GET", selection, "operator", 200, org=org)).json()
    selected = (await call("PUT", selection, "admin", 200, org=org, headers={"If-Match": f'"{prior["version"]}"'},
                           json={"mode_id": "blue"})).json()
    request = {"permission_id": permission_id, "permission_revision": 1, "selection_version": selected["version"],
               "sources": [source["digest"]], "event_rule": "identity-login-failure-v1"}
    analyses_path = project_root + "/analyses"
    key = {"Idempotency-Key": "blue-analysis-draft-once"}
    await call("POST", analyses_path, "operator", 422, org=org, headers=key, json={**request, "event_rule": "arbitrary-rule"})
    draft = (await call("POST", analyses_path, "operator", 201, org=org, headers=key, json=request)).json()
    analysis = f"{analyses_path}/{draft['id']}"
    step = analysis + "/steps/event-review"
    step_key = {"Idempotency-Key": "blue-analysis-advance-once"}
    await call("POST", step, "operator", 422, org=org, headers=step_key, json={"strategy": "assisted"})
    completed = (await call("POST", step, "operator", 200, org=org, headers=step_key, json={})).json()
    assert completed["state"] == "completed"
    assert (await call("POST", step, "operator", 200, org=org, headers=step_key, json={})).json() == completed
    review = (await call("GET", analysis + "/review", "approver", 200, org=org)).json()
    item, = review["conclusions"]
    assert item["status"] == "observed" and item["citations"] == [source["digest"]]
    assert item["triage"] == {"rule_id": request["event_rule"], "batches_evaluated": 1, "matching_events": 1}
    await call("PUT", analysis + "/review/decisions/" + item["id"], "approver", 200, org=org,
               json={"decision": "approve", "reason": "Synthetic triage verified"})
    await call("PUT", analysis + "/publication", "approver", 200, org=org)
    report = (await call("GET", analysis + "/publication/report", "operator", 200, org=org)).text
    assert request["event_rule"] in report and "<dt>Eventos coincidentes</dt><dd>1</dd>" in report
    assert event["event_id"] not in report
    await call("PUT", upload + "/disposition", "approver", 200, org=org, json={"reason": "Withdraw event source"})
    await call("PUT", upload, "operator", 409, org=org, headers=headers, data=payload)
    hidden = await call("GET", analysis + "/publication/report", "operator", 404, org=org)
    assert hidden.json()["code"] == "analysis_publication_not_found"
    await check_purple_coverage(call, org, path, spec, source, payload, selected["version"])


async def check_purple_coverage(call, org, path, base_spec, source, payload, previous_selection):
    mode = TEAM_CATALOG[TeamId.PURPLE]
    receipt = (await call("POST", path, "operator", 201, org=org, headers={"Idempotency-Key": "purple-batch-permission"},
                          json={**base_spec, "mode_id": mode.id.value, "mode_digest": mode.digest,
                                "mode_version": mode.version, "sources": [source]})).json()
    permission = f"{path}/{receipt['id']}"
    await call("POST", permission + "/decisions", "approver", 200, org=org,
               json={"revision": 1, "decision": "approve", "reason": "Purple evidence approved"})
    upload = f"{permission}/revisions/1/sources/{source['digest']}"
    await call("PUT", upload, "operator", 200, org=org, headers={"Content-Type": "application/json"}, data=payload)
    root = path.removesuffix("/evidence-permissions")
    selection = (await call("PUT", root + "/team-selection", "admin", 200, org=org,
                            headers={"If-Match": f'"{previous_selection}"'}, json={"mode_id": "purple"})).json()
    scenario = {"scenario_id": str(uuid4()), "target_id": source["target_id"], "checks": [
        {"control_id": control, "rule_id": "identity-login-failure-v1",
         "window_start": f"2026-01-01T{start}:00Z", "window_end": f"2026-01-01T{end}:00Z"}
        for control, start, end in (("hit", "14:00", "14:30"), ("negative", "13:00", "14:00"), ("gap", "14:45", "15:45"))
    ]}
    body = {"permission_id": receipt["id"], "permission_revision": 1, "selection_version": selection["version"],
            "sources": [source["digest"]]}
    key = {"Idempotency-Key": "purple-coverage-draft-once"}
    await call("POST", root + "/analyses", "operator", 422, org=org, headers=key, json=body)
    await call("POST", root + "/analyses", "operator", 422, org=org, headers=key,
               json={**body, "coverage_scenario": {**scenario, "target_id": str(uuid4())}})
    draft = (await call("POST", root + "/analyses", "operator", 201, org=org, headers=key,
                        json={**body, "coverage_scenario": scenario})).json()
    analysis = f"{root}/analyses/{draft['id']}"
    step = analysis + "/steps/coverage-comparison"
    key = {"Idempotency-Key": "purple-coverage-step-once"}
    await call("POST", step, "operator", 422, org=org, headers=key, json={"strategy": "assisted"})
    assert (await call("POST", step, "operator", 200, org=org, headers=key, json={})).json()["state"] == "completed"
    item, = (await call("GET", analysis + "/review", "approver", 200, org=org)).json()["conclusions"]
    matrix = item["coverage"]
    assert (matrix["detected"], matrix["evaluated"]) == (1, 2)
    assert [(row["status"], row["citations"]) for row in matrix["rows"]] == [
        (status, [source["digest"]]) for status in ("detected", "not_detected", "no_data")
    ]
    await call("PUT", analysis + "/review/decisions/" + item["id"], "approver", 200, org=org,
               json={"decision": "approve", "reason": "Synthetic scenario verified"})
    await call("PUT", analysis + "/publication", "approver", 200, org=org)
    report = (await call("GET", analysis + "/publication/report", "operator", 200, org=org)).text
    assert "<dt>Controles evaluados</dt><dd>2</dd>" in report and "Sin datos suficientes" in report
    await call("PUT", upload + "/disposition", "approver", 200, org=org, json={"reason": "Withdraw coverage evidence"})
    await call("GET", analysis + "/publication/report", "operator", 404, org=org)


async def check_analysis_ledger(call, admin, store, cipher, org, project, users, path, base_spec, legacy, inference):
    scope = UUID(org), UUID(project)
    operator = users["operator"]
    second_operator = uuid4()
    with admin.begin() as connection:
        connection.execute(text("""
            INSERT INTO pentest_agent.identity (id, issuer, subject) VALUES (:actor, 'issuer', 'ledger-second-operator')
        """), {"actor": second_operator})
        connection.execute(text("""
            INSERT INTO pentest_agent.organization_membership (org_id, user_id, role_id)
            VALUES (:org, :actor, 'member')
        """), {"org": org, "actor": second_operator})
        connection.execute(text("""
            INSERT INTO pentest_agent.project_membership (org_id, project_id, user_id, role_id)
            VALUES (:org, :project, :actor, 'operator')
        """), {"org": org, "project": project, "actor": second_operator})
    selection_url = path + "/team-selection"
    current = (await call("GET", selection_url, "operator", 200, org=org)).json()
    rainbow = (await call("PUT", selection_url, "admin", 200, org=org,
                          headers={"If-Match": f'"{current["version"]}"'}, json={"mode_id": "rainbow"})).json()
    mode = TEAM_CATALOG[TeamId.RAINBOW]
    spec = PermissionSpec.model_validate({
        **base_spec, "mode_id": mode.id, "mode_version": mode.version, "mode_digest": mode.digest,
        "sources": [{**legacy, "capability": ToolId.SCOPE_RECORD_REVIEW}], "allow_local_inference": True,
    })

    def prepare(actor, key="ledger-permission-001"):
        with store.project(actor, *scope, Action.REQUEST_EVIDENCE) as (connection, caller):
            permission = evidence.request_permission(connection, caller, spec, key)
        with store.project(users["approver"], *scope, Action.DECIDE_EVIDENCE) as (connection, caller):
            evidence.decide(connection, caller, permission["id"], permission["revision"], "approve", "Fixture approved")
        return AnalysisDraft(permission_id=permission["id"], permission_revision=1, selection_version=rainbow["version"],
                             sources=(legacy["digest"],))

    request = prepare(operator)
    other_request = prepare(second_operator)

    def create(actor, data, key):
        with store.project(actor, *scope, Action.REQUEST_EVIDENCE) as (connection, caller):
            return analyses.create_draft(connection, caller, cipher, data, key)

    one, replay = await asyncio.gather(*[
        asyncio.to_thread(create, operator, request, "ledger-draft-0001") for _ in range(2)
    ])
    assert one == replay
    assert one["snapshot"]["status"] == "draft" and one["snapshot"]["manifest_digest"] == mode.digest
    assert set(one["snapshot"]["stage_manifests"]) == {step.id for step in mode.workflow}
    assert one["snapshot"]["plan_hash"] == base_spec["plan_hash"]
    with pytest.raises(AccessError, match="idempotency_conflict"):
        create(operator, request.model_copy(update={"selection_version": 100}), "ledger-draft-0001")
    two = create(operator, request, "ledger-draft-0002")
    other = create(second_operator, other_request, "ledger-draft-0001")
    with pytest.raises(RuntimeError, match="transaction aborted"):
        with store.project(operator, *scope, Action.REQUEST_EVIDENCE) as (connection, caller):
            failed = analyses.create_draft(connection, caller, cipher, request, "ledger-rollback-001")
            raise RuntimeError("transaction aborted")
    with store.project(operator, *scope, Action.REQUEST_EVIDENCE) as (connection, caller):
        with pytest.raises(AccessError, match="analysis_not_found"):
            analyses.get_draft(connection, caller, failed["id"])
        assert len(analyses.events(connection, caller, one["id"])) == 1
        assert connection.scalar(text("""
            SELECT count(*) FROM pentest_agent.offline_analysis WHERE snapshot->>'permission_id' = :id
        """), {"id": str(request.permission_id)}) == 2

    queued = {name: create(operator, request, f"dispatch-draft-{name}")["id"]
              for name in ("normal", "missing", "archive", "timeout", "foreign")}
    revoke_request = prepare(operator, "dispatch-revocable-permission")
    queued["revoke"] = create(operator, revoke_request, "dispatch-draft-revoke")["id"]
    await check_analysis_api(call, admin, org, project, users, path, request, inference)

    stop_id = create(operator, request, "lifecycle-stop-draft")["id"]

    await call("PUT", selection_url, "admin", 200, org=org,
               headers={"If-Match": f'"{rainbow["version"]}"'}, json={"mode_id": "yellow"})
    assert create(operator, request, "ledger-draft-0001") == one
    with pytest.raises(AccessError, match="analysis_selection_changed"):
        create(operator, request, "ledger-draft-0004")

    def reserve(actor, draft, key, step="white", usage=Usage(input_bytes=10)):
        try:
            with store.project(actor, *scope, Action.REQUEST_EVIDENCE) as (connection, caller):
                return analyses.reserve_step(connection, caller, draft["id"], key, step, usage)
        except AccessError as error:
            return error.code

    first = reserve(operator, one, "ledger-step-00001", usage=Usage(calls=1, input_tokens=9000))
    assert isinstance(first, dict) and not first["replayed"]
    assert reserve(operator, one, "ledger-step-00001", usage=Usage(calls=1, input_tokens=9000)) == {
        **first, "replayed": True,
    }
    assert reserve(operator, one, "ledger-step-00001") == "idempotency_conflict"
    assert reserve(operator, one, "ledger-step-00002", "unknown") == "unknown_analysis_step"
    outcomes = await asyncio.gather(
        asyncio.to_thread(reserve, operator, two, "ledger-step-00003"),
        asyncio.to_thread(reserve, second_operator, other, "ledger-step-00003"),
    )
    assert sum(result == "analysis_project_busy" for result in outcomes) == 1
    winner_index = next(i for i, result in enumerate(outcomes) if isinstance(result, dict))
    winner_actor, winner_draft = [(operator, two), (second_operator, other)][winner_index]
    with store.project(operator, *scope, Action.REQUEST_EVIDENCE) as (connection, caller):
        measured = Usage(calls=1, input_tokens=8000)
        settled = analyses.settle_step(connection, caller, one["id"], first["id"], measured)
        assert settled["outcome"] == "measured" and settled["input_tokens"] == 8000
        assert analyses.settle_step(connection, caller, one["id"], first["id"], measured) == settled
        assert [(event["sequence"], event["kind"]) for event in analyses.events(connection, caller, one["id"])] == [
            (1, "draft_recorded"), (2, "step_reserved"), (3, "step_settled"),
        ]
    assert reserve(operator, one, "ledger-step-00004", "blue",
                   Usage(calls=1, input_tokens=4001)) == "analysis_budget_exceeded"
    pending = outcomes[winner_index]
    with admin.begin() as connection:
        connection.execute(text("""
            UPDATE pentest_agent.analysis_reservation
            SET started_at = clock_timestamp() - interval '3 seconds',
                expires_at = clock_timestamp() - interval '1 second'
            WHERE id = :id
        """), {"id": pending["id"]})
    with store.project(winner_actor, *scope, Action.REQUEST_EVIDENCE) as (connection, caller):
        assert analyses.reconcile_expired(connection, caller, winner_draft["id"]) == 1
        assert analyses.reconcile_expired(connection, caller, winner_draft["id"]) == 0
        timed_out = analyses.settle_step(connection, caller, winner_draft["id"], pending["id"], Usage())
        assert timed_out["outcome"] == "timeout" and timed_out["input_bytes"] == 10
    unknown = reserve(operator, one, "ledger-step-00005", "blue")
    with store.project(operator, *scope, Action.REQUEST_EVIDENCE) as (connection, caller):
        charged = analyses.settle_step(connection, caller, one["id"], unknown["id"])
        assert charged["outcome"] == "unknown" and charged["input_bytes"] == 10
    with admin.begin() as connection:
        connection.execute(text("""
            UPDATE pentest_agent.analysis_reservation
            SET started_at = clock_timestamp() - interval '121 seconds'
            WHERE id = :id
        """), {"id": first["id"]})
    assert reserve(operator, one, "ledger-step-00006", "purple") == "analysis_deadline_elapsed"
    await check_analysis_dispatch(admin, store, cipher, scope, users, queued, revoke_request, second_operator)

    stop_path = f"/organizations/{org}/stop"
    stop = (await call("GET", stop_path, "admin", 200)).json()
    dispatch = PostgresDispatch(store, cipher, *scope, operator)
    tools = frozenset({ToolId.SCOPE_RECORD_REVIEW})
    stop_work = dispatch.start(stop_id, "white", "lifecycle-org-stop", tools, assisted=True, inference_available=True)
    stop_proposal = generate_proposal(stop_work.prepared, inference.model, inference)
    stopped = (await call("PUT", stop_path, "admin", 200, headers={"If-Match": f'"{stop["revision"]}"'},
                          json={"enabled": True, "reason": "Pause ledger fixture"})).json()
    stop_receipt = dispatch.finish(stop_id, "white", "lifecycle-org-stop", stop_work.reservation_id,
                                   output=StepOutput(status="inconclusive"), failure=None, proposal=stop_proposal)
    assert stop_receipt["state"] == "blocked" and stop_receipt["reason"] == "plan_state_changed"
    assert_private_analysis_result(admin, stop_id, None, None)
    assert reserve(operator, two, "ledger-step-00007") == "plan_state_changed"
    await call("PUT", stop_path, "admin", 200, headers={"If-Match": f'"{stopped["revision"]}"'},
               json={"enabled": False, "reason": "Close ledger fixture"})
    assert reserve(operator, two, "ledger-step-00007") == "analysis_stop_changed"
    current = (await call("GET", selection_url, "operator", 200, org=org)).json()
    selected = (await call("PUT", selection_url, "admin", 200, org=org,
                            headers={"If-Match": f'"{current["version"]}"'}, json={"mode_id": "rainbow"})).json()
    mandate_request = request.model_copy(update={"selection_version": selected["version"]})
    mandate_id = create(operator, mandate_request, "lifecycle-mandate-draft")["id"]
    work = dispatch.start(mandate_id, "white", "lifecycle-stale-mandate", tools, assisted=True, inference_available=True)
    return dispatch, mandate_id, work


async def check_analysis_dispatch(admin, store, cipher, scope, users, drafts, revoke_request, other_operator):
    port = PostgresDispatch(store, cipher, *scope, users["operator"])
    tool = ToolId.SCOPE_RECORD_REVIEW
    started, release = Event(), Event()
    calls = []

    def wait_and_observe(work):
        assert store.engine.pool.checkedout() == 0
        calls.append(work.inputs)
        started.set()
        if not release.wait(10):
            raise RuntimeError("fixture handler timed out")
        return StepOutput(status="observed", citations=(work.inputs[0].digest,))

    assert port.state(drafts["normal"]) == "draft"
    task = asyncio.create_task(asyncio.to_thread(
        dispatch_step, port, {tool: wait_and_observe}, drafts["normal"], "white", "dispatcher-same-key"
    ))
    try:
        assert await asyncio.to_thread(started.wait, 10)
        assert port.state(drafts["normal"]) == "processing"
        replay = dispatch_step(port, {tool: wait_and_observe}, drafts["normal"], "white", "dispatcher-same-key")
        assert replay["state"] == "processing"
        with pytest.raises(AccessError, match="idempotency_conflict"):
            port.start(drafts["normal"], "red", "dispatcher-same-key", frozenset({tool}))
    finally:
        release.set()
    complete = await task
    assert complete["state"] == "completed" and len(calls) == 1
    assert port.state(drafts["normal"]) == "ready"
    assert dispatch_step(port, {}, drafts["normal"], "white", "dispatcher-same-key") == complete
    assert calls[0][0].source.origin == "legacy"

    unavailable = dispatch_step(port, {}, drafts["missing"], "white", "dispatcher-missing-key")
    assert unavailable["reason"] == "analysis_capability_unavailable"
    assert port.state(drafts["missing"]) == "blocked"
    with admin.begin() as connection:
        connection.execute(text("UPDATE pentest_agent.project SET state = 'archived' WHERE org_id = :org AND id = :project"),
                           {"org": scope[0], "project": scope[1]})
    try:
        archived = dispatch_step(port, {tool: wait_and_observe}, drafts["archive"], "white", "dispatcher-archived-key")
        assert archived["reason"] == "project_archived"
    finally:
        with admin.begin() as connection:
            connection.execute(text("UPDATE pentest_agent.project SET state = 'active' WHERE org_id = :org AND id = :project"),
                               {"org": scope[0], "project": scope[1]})
    foreign = PostgresDispatch(store, cipher, *scope, other_operator)
    with pytest.raises(AccessError, match="analysis_not_found"):
        foreign.start(drafts["foreign"], "white", "dispatcher-foreign-key", frozenset({tool}))

    def revoke_then_observe(work):
        with store.project(users["approver"], *scope, Action.DECIDE_EVIDENCE) as (connection, caller):
            evidence.decide(connection, caller, revoke_request.permission_id, 1, "revoke", "Revoked in fixture")
        return StepOutput(status="observed", citations=(work.inputs[0].digest,))

    revoked = dispatch_step(port, {tool: revoke_then_observe}, drafts["revoke"], "white", "dispatcher-revoke-key")
    assert revoked["state"] == "blocked" and revoked["reason"] == "evidence_permission_inactive"
    with admin.connect() as connection:
        outcomes = connection.execute(text("""
            SELECT analysis_id, output FROM pentest_agent.analysis_step_outcome WHERE analysis_id IN (:completed, :blocked)
        """), {"completed": drafts["normal"], "blocked": drafts["revoke"]}).all()
    assert dict(outcomes) == {
        drafts["normal"]: {"status": "observed", "citations": [calls[0][0].digest]},
        drafts["revoke"]: None,
    }
    work = port.start(drafts["timeout"], "white", "dispatcher-timeout-key", frozenset({tool}))
    with admin.begin() as connection:
        connection.execute(text("""
            UPDATE pentest_agent.analysis_reservation
            SET started_at = clock_timestamp() - interval '3 seconds',
                expires_at = clock_timestamp() - interval '1 second'
            WHERE id = :id
        """), {"id": work.reservation_id})
    timed_out = dispatch_step(port, {tool: wait_and_observe}, drafts["timeout"], "white", "dispatcher-timeout-key")
    assert timed_out["state"] == "failed" and timed_out["reason"] == "analysis_step_timeout"
    assert len(calls) == 1


def assert_private_analysis_result(admin, analysis_id, status, proposal):
    with admin.connect() as connection:
        output, receipt = connection.execute(text("""
            SELECT output, proposal_receipt FROM pentest_agent.analysis_step_outcome WHERE analysis_id = :id
        """), {"id": analysis_id}).one()
    assert (output["status"] if output else None) == status
    assert (receipt["proposal"]["kind"] if receipt and receipt["proposal"] else None) == proposal
    if proposal:
        assert receipt["model"]["id"] == "postgres-fixture"
        assert receipt["policy_version"] == "offline-proposals-v1"


async def check_analysis_publication(call, admin, store, cipher, org, project, users, path, spec, source, payload, inference):
    selection_url = path + "/team-selection"
    previous = (await call("GET", selection_url, "operator", 200, org=org)).json()
    selection = (await call("PUT", selection_url, "admin", 200, org=org,
                            headers={"If-Match": f'"{previous["version"]}"'}, json={"mode_id": "white"})).json()
    team = TEAM_CATALOG[TeamId.WHITE]
    step = team.execution_order()[0]
    digest = source["digest"]

    async def prepare(label):
        perm = (await call("POST", path + "/evidence-permissions", "operator", 201, org=org,
                           headers={"Idempotency-Key": f"publication-perm-{label}"},
                           json={**spec, "mode_id": team.id, "mode_version": team.version, "mode_digest": team.digest,
                                 "allow_local_inference": True, "sources": [source]})).json()
        permission = f"{path}/evidence-permissions/{perm['id']}"
        await call("POST", permission + "/decisions", "approver", 200, org=org,
                   json={"revision": 1, "decision": "approve", "reason": "Authorized fixture"})
        upload = f"{permission}/revisions/1/sources/{digest}"
        await call("PUT", upload, "operator", 200, org=org, headers={"Content-Type": "application/json"}, data=payload)
        created = (await call("POST", path + "/analyses", "operator", 201, org=org,
                              headers={"Idempotency-Key": f"publication-draft-{label}"},
                              json={"permission_id": perm["id"], "permission_revision": 1,
                                    "selection_version": selection["version"], "sources": [digest]})).json()
        return f"{path}/analyses/{created['id']}", created["id"], upload

    async def complete_run(route, label):
        inference.body = json.dumps({"kind": "draft", "observation": {"control": "logging", "result": "observed"},
                                     "citations": [digest]}).encode()
        try:
            receipt = (await call("POST", f"{route}/steps/{step}", "operator", 200, org=org,
                                  headers={"Idempotency-Key": f"publication-advance-{label}"},
                                  json={"strategy": "assisted"})).json()
        finally:
            inference.body = b'{"kind":"abstain"}'
        assert receipt["state"] == "completed" and receipt["proposal_error"] is None

    route, analysis_id, upload = await prepare("normal")
    approval_reason = '<script>alert("x")</script> https://example.invalid/'
    approval = {"decision": "approve", "reason": approval_reason}
    rejection = {"decision": "reject", "reason": "Duplicate of the reviewed control"}
    observation_url = f"{route}/review/decisions/{step}.observation"
    draft_url = f"{route}/review/decisions/{step}.draft"
    report_url = f"{route}/publication/report"
    await call("GET", route + "/review", "approver", 409, org=org)
    await complete_run(route, "normal")
    await call("GET", route + "/review", "operator", 403, org=org)
    await call("PUT", route + "/publication", "operator", 403, org=org)
    await call("GET", route + "/review", "approver", 404, org=uuid4())
    review = (await call("GET", route + "/review", "approver", 200, org=org)).json()
    assert review["author_id"] == str(users["operator"])
    assert [(item["id"], item["citations"]) for item in review["conclusions"]] == [
        (f"{step}.observation", [digest]), (f"{step}.draft", [digest]),
    ]
    await call("PUT", route + "/publication", "approver", 409, org=org)
    await call("PUT", observation_url, "approver", 200, org=org, json=rejection)
    decision = (await call("PUT", draft_url, "approver", 200, org=org, json=approval)).json()
    assert decision["reason"] == approval_reason and decision["actor_id"] == str(users["approver"])
    assert (await call("PUT", draft_url, "approver", 200, org=org, json=approval)).json() == decision
    await call("PUT", draft_url, "approver", 409, org=org, json=rejection)
    membership = text("""
        UPDATE pentest_agent.project_membership SET role_id = :role
        WHERE org_id = :org AND project_id = :project AND user_id = :actor
    """)
    scope = {"org": org, "project": project, "actor": users["approver"]}
    with admin.begin() as connection:
        connection.execute(membership, {**scope, "role": "viewer"})
        competing_publication = asyncio.create_task(call("PUT", route + "/publication", "approver", 403, org=org))
        for _ in range(200):
            if connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND NOT granted)")):
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("Publication did not wait on the in-flight membership change")
    try:
        assert (await competing_publication).json()["code"] == "permission_denied"
    finally:
        with admin.begin() as connection:
            connection.execute(membership, {**scope, "role": "approver"})
    first, second = await asyncio.gather(*[
        call("PUT", route + "/publication", "approver", 200, org=org) for _ in range(2)
    ])
    assert first.json() == second.json()
    assert first.json()["analysis_id"] == analysis_id
    assert (await call("GET", route, "operator", 200, org=org)).json()["state"] == "published"
    assert (await call("GET", route + "/review", "approver", 200, org=org)).json()["publication"] == first.json()
    cancelled = await call("PUT", route + "/cancellation", "operator", 409, org=org)
    assert cancelled.json()["code"] == "analysis_already_published"
    report = await call("GET", report_url, "operator", 200, org=org)
    assert report.content == (await call("GET", report_url, "approver", 200, org=org)).content
    assert sha256(report.content).hexdigest() == first.json()["report_digest"]
    assert "&lt;script&gt;" in report.text and "<script>" not in report.text
    assert f"{step}.draft" in report.text and f"{step}.observation" not in report.text
    assert "postgres-fixture" in report.text and digest in report.text and '<a href="https://example.invalid/' not in report.text
    await call("GET", report_url, "viewer", 404, org=org)
    other_reviewer = {**scope, "actor": users["admin"]}
    with admin.begin() as connection:
        connection.execute(membership, {**other_reviewer, "role": "approver"})
    try:
        await call("GET", route + "/review", "admin", 404, org=org)
        await call("GET", report_url, "admin", 404, org=org)
    finally:
        with admin.begin() as connection:
            connection.execute(membership, {**other_reviewer, "role": "project_admin"})
    store.engine.dispose()
    origin = "https://app.example"
    restarted = build_app(RequestAuth(Authentication(EngagementProvider(), store), origin), store, cipher=cipher)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=origin) as client:
        after_restart = await client.get(f"/api/v1{report_url}", params={"org_id": org},
                                         headers={"Authorization": "Bearer operator"})
    assert after_restart.status_code == 200 and report.content == after_restart.content

    await call("PUT", upload + "/disposition", "approver", 200, org=org, json={"reason": "Withdraw dependency"})
    await call("GET", report_url, "operator", 404, org=org)
    await call("GET", report_url, "approver", 404, org=org)
    await call("PUT", route + "/publication", "approver", 404, org=org)
    with tenant_transaction(store.engine, org_id=UUID(org), project_id=UUID(project),
                            user_id=users["operator"]) as connection:
        assert connection.scalar(text("SELECT count(*) FROM pentest_agent.analysis_publication")) == 0

    stale, stale_id, stale_upload = await prepare("withdrawn")
    await complete_run(stale, "withdrawn")
    for kind in ("observation", "draft"):
        await call("PUT", f"{stale}/review/decisions/{step}.{kind}", "approver", 200, org=org, json=approval)
    await call("PUT", stale_upload + "/disposition", "approver", 200, org=org, json={"reason": "Withdraw before publication"})
    await call("PUT", stale + "/publication", "approver", 404, org=org)

    foreign, foreign_id, _ = await prepare("foreign")
    await complete_run(foreign, "foreign")
    with admin.begin() as connection:
        connection.execute(text("""
            UPDATE pentest_agent.analysis_step_outcome
              SET output = jsonb_build_object('status', 'observed', 'citations', jsonb_build_array(CAST(:digest AS text)))
              WHERE analysis_id = :analysis_id
        """), {"analysis_id": foreign_id, "digest": "c" * 64})
    denied = await call("PUT", foreign + "/publication", "approver", 409, org=org)
    assert denied.json()["code"] == "analysis_reference_invalid"
    with admin.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM pentest_agent.analysis_publication WHERE analysis_id = :id"),
                                 {"id": stale_id}) == 0


async def check_analysis_api(call, admin, org, project, users, path, request, inference):
    route = path + "/analyses"
    body = request.model_dump(mode="json")

    async def create(label):
        return (await call("POST", route, "operator", 201, org=org, json=body,
                           headers={"Idempotency-Key": f"lifecycle-create-{label}"})).json()

    async def advance(analysis_id, key, status=200, strategy="assisted"):
        return await call("POST", f"{route}/{analysis_id}/steps/white", "operator", status, org=org,
                          headers={"Idempotency-Key": key}, json={"strategy": strategy})

    async def read(analysis_id):
        return (await call("GET", f"{route}/{analysis_id}", "operator", 200, org=org)).json()

    async def expire(reservation_id):
        with admin.begin() as connection:
            connection.execute(text("""
                UPDATE pentest_agent.analysis_reservation
                SET started_at = clock_timestamp() - interval '3 seconds',
                    expires_at = clock_timestamp() - interval '1 second'
                WHERE id = :id
            """), {"id": reservation_id})

    await call("POST", route, "operator", 428, org=org, json=body)
    item, replay = await asyncio.gather(create("one"), create("one"))
    assert item == replay
    analysis = item["id"]
    assert (await read(analysis))["state"] == "draft"
    await call("GET", f"{route}/{analysis}", "viewer", 403, org=org)
    await call("GET", f"{route}/{analysis}", "operator", 404, org=uuid4())
    await call("POST", f"{route}/{analysis}/steps/white", "operator", 422, org=org,
               headers={"Idempotency-Key": "lifecycle-extra-param"}, json={"command": "fixture"})

    async def pause_provider(analysis_id, label, concurrent_action, final_status=200):
        started, release = Event(), Event()
        key = f"lifecycle-advance-{label}"

        def blocked():
            started.set()
            if not release.wait(8):
                raise TimeoutError

        inference.during_call = blocked
        before = inference.calls
        worker = asyncio.create_task(advance(analysis_id, key, final_status))
        try:
            assert await asyncio.to_thread(started.wait, 8)
            await concurrent_action(key)
        finally:
            release.set()
            try:
                response = await worker
            finally:
                inference.during_call = None
        assert inference.calls == before + 1
        return response.json()

    async def advance_twice(key):
        assert (await read(analysis))["state"] == "processing"
        assert (await advance(analysis, key)).json()["state"] == "processing"
        assert (await advance(analysis, key, 409, strategy="deterministic")).json()["code"] == "idempotency_conflict"
        assert (await advance(analysis, "lifecycle-competing-key", 409)).json()["code"] == "analysis_busy"

    receipt = await pause_provider(analysis, "normal", advance_twice)
    assert receipt["state"] == "completed"
    assert (await advance(analysis, "lifecycle-advance-normal")).json() == receipt
    detail = await read(analysis)
    assert detail["state"] == "ready" and detail["snapshot_digest"] == item["snapshot_digest"]
    assert detail["steps"] == [receipt]
    assert "citations" not in json.dumps(detail)
    assert_private_analysis_result(admin, analysis, "observed", "abstain")
    with pytest.raises(DBAPIError) as private_receipt:
        with tenant_transaction(inference.store.engine, org_id=UUID(org), project_id=UUID(project),
                                user_id=users["operator"]) as connection:
            connection.scalar(text("""
                SELECT proposal_receipt FROM pentest_agent.analysis_step_outcome WHERE analysis_id = :analysis
            """), {"analysis": analysis})
    assert private_receipt.value.orig.sqlstate == "42501"

    deterministic = (await create("deterministic"))["id"]
    before = inference.calls
    result = (await advance(deterministic, "lifecycle-advance-deterministic", strategy="deterministic")).json()
    assert result["state"] == "completed" and result["proposal_error"] is None
    assert inference.calls == before
    assert_private_analysis_result(admin, deterministic, "observed", None)

    missing_id = (await create("missing"))["id"]

    def unavailable():
        raise ProposalDependencyMissing

    inference.during_call = unavailable
    try:
        missing = (await advance(missing_id, "lifecycle-advance-missing")).json()
    finally:
        inference.during_call = None
    assert missing["state"] == "completed" and missing["proposal_error"] == "proposal_dependency_missing"
    assert_private_analysis_result(admin, missing_id, "observed", None)

    cancelled_id = (await create("cancel"))["id"]

    async def cancel_while_running(_key):
        url = f"{route}/{cancelled_id}/cancellation"
        result = (await call("PUT", url, "operator", 200, org=org)).json()
        assert (await call("PUT", url, "operator", 200, org=org)).json() == result
        assert result["state"] == "cancelled"

    cancelled = await pause_provider(cancelled_id, "cancel", cancel_while_running)
    assert cancelled["reason"] == "analysis_cancelled"
    assert (await advance(cancelled_id, "lifecycle-after-cancel", 409)).json()["code"] == "analysis_cancelled"
    assert (await read(cancelled_id))["state"] == "cancelled"
    assert_private_analysis_result(admin, cancelled_id, None, None)

    elapsed_id = (await create("expired"))["id"]

    async def expire_while_running(_key):
        step = (await read(elapsed_id))["steps"][0]
        await expire(step["reservation_id"])
        state = await read(elapsed_id)
        assert state["state"] == "failed" and state["steps"][0]["reason"] == "analysis_step_timeout"

    elapsed = await pause_provider(elapsed_id, "expire", expire_while_running)
    assert elapsed["reason"] == "analysis_step_timeout"
    assert_private_analysis_result(admin, elapsed_id, None, None)

    revoked_id = (await create("membership"))["id"]
    membership = text("""
        UPDATE pentest_agent.project_membership SET role_id = :role
        WHERE org_id = :org AND project_id = :project AND user_id = :user
    """)
    scope = {"org": org, "project": project, "user": users["operator"]}
    reservation_id = None

    async def revoke_membership(_key):
        nonlocal reservation_id
        reservation_id = (await read(revoked_id))["steps"][0]["reservation_id"]
        with admin.begin() as connection:
            connection.execute(membership, {**scope, "role": "viewer"})

    try:
        revoked = await pause_provider(revoked_id, "membership", revoke_membership, final_status=403)
        assert revoked["code"] == "permission_denied"
    finally:
        with admin.begin() as connection:
            connection.execute(membership, {**scope, "role": "operator"})
    await expire(reservation_id)
    assert (await read(revoked_id))["state"] == "failed"
    assert_private_analysis_result(admin, revoked_id, None, None)


async def check_upload_admission(call, admin, runtime, org, other_org, project, operator, uploads):
    async def unexpected_body():
        pytest.fail("Upload read the body before checking project access")
        yield b""

    def role(value):
        with admin.begin() as connection:
            connection.execute(text("""
                UPDATE pentest_agent.project_membership SET role_id = :role
                WHERE org_id = :org AND project_id = :project AND user_id = :operator
            """), {"org": org, "project": project, "operator": operator, "role": value})

    async def change_membership_while_streaming(content):
        assert runtime.pool.checkedout() == 0
        role("viewer")
        yield content

    for path, headers, query, content in uploads:
        await call("POST", path, "viewer", 403, org=org, headers=headers, query=query, data=unexpected_body())
        await call("POST", path, "operator", 404, org=other_org, headers=headers, query=query, data=unexpected_body())
        try:
            await call("POST", path, "operator", 403, org=org, headers=headers, query=query,
                       data=change_membership_while_streaming(content))
        finally:
            role("operator")


async def check_scope_reviews(call, admin, org, project, path, target, authorization_id):
    target_id = (await call("POST", path + "/targets", "operator", 201, org=org,
                            json={**target, "slug": "scope-asset"})).json()["id"]
    second_id = (await call("POST", path + "/targets", "operator", 201, org=org,
                            json={**target, "slug": "second-scope-asset", "address": "example.net"})).json()["id"]
    assessments = path + "/assessments"
    plans = path + "/plans"
    await call("POST", assessments, "viewer", 403, org=org, json={"label": "Paperwork review"})
    assessment = (await call("POST", assessments, "operator", 201, org=org,
                             json={"label": "Paperwork review"})).json()
    assert (await call("GET", assessments, "viewer", 200, org=org)).json()["items"] == [assessment]
    body = {"assessment_id": assessment["id"], "authorization_id": authorization_id,
            "authorization_revision": 1, "target_ids": [target_id, second_id]}
    headers = {"Idempotency-Key": "review-request-0001"}
    await call("POST", plans, "operator", 428, org=org, json=body)
    await call("POST", plans, "operator", 422, org=org, json={**body, "target_ids": [target_id, target_id]},
               headers=headers)

    responses = await asyncio.gather(
        call("POST", plans, "operator", 201, org=org, json=body, headers=headers),
        call("POST", plans, "operator", 201, org=org,
             json={**body, "target_ids": [second_id, target_id]}, headers=headers),
    )
    result = responses[0].json()
    assert result == responses[1].json()
    assert result["status"] == "reviewed" and result["execution"] == "disabled"
    assert sorted(item["reason"] for item in result["targets"]) == ["allowed", "allowed"]

    plan_path = plans + f"/{result['id']}"
    assert (await call("GET", plan_path, "viewer", 200, org=org)).json() == result
    events = (await call("GET", plan_path + "/events", "viewer", 200, org=org)).json()["items"]
    assert [event["kind"] for event in events] == ["scope_review_recorded"]
    with admin.connect() as connection:
        assert connection.scalar(text("""
            SELECT count(*) FROM pentest_agent.assessment_plan_outbox
            WHERE plan_id = :plan AND event_id = :event
        """), {"plan": result["id"], "event": events[0]["id"]}) == 1

    conflict = await call("POST", plans, "operator", 409, org=org, headers=headers,
                          json={**body, "target_ids": [target_id]})
    assert conflict.json()["code"] == "idempotency_conflict"
    invalid_hash = await call("POST", plan_path + "/verify", "viewer", 409, org=org, json={"hash": "0" * 64})
    assert invalid_hash.json()["code"] == "plan_hash_mismatch"
    assert (await call("POST", plan_path + "/verify", "viewer", 200, org=org,
                       json={"hash": result["hash"]})).json()["status"] == "verified"

    duplicate = (await call("POST", plans, "operator", 201, org=org, json=body,
                          headers={"Idempotency-Key": "review-request-0002"})).json()
    assert duplicate["hash"] == result["hash"] and duplicate["id"] != result["id"]
    await call("POST", plans, "operator", 404, org=org, json={**body, "target_ids": [str(uuid4())]},
               headers={"Idempotency-Key": "review-request-0003"})
    await call("PATCH", path + f"/targets/{target_id}", "operator", 200, org=org,
               headers={"If-Match": '"1"'}, json={"slug": "versioned-scope-asset"})
    stale = await call("POST", plan_path + "/verify", "viewer", 409, org=org, json={"hash": result["hash"]})
    assert stale.json()["code"] == "plan_state_changed"
    refreshed = (await call("POST", plans, "operator", 201, org=org, json=body,
                            headers={"Idempotency-Key": "review-request-0004"})).json()
    assert refreshed["hash"] != result["hash"]
    current_path = plans + f"/{refreshed['id']}"
    await call("POST", current_path + "/verify", "viewer", 200, org=org, json={"hash": refreshed["hash"]})
    return current_path
