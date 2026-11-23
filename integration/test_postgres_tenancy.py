"""Exercise the migration against a disposable PostgreSQL database."""

import asyncio
import os
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

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
from application.authentication import Authentication, Identity
from application.documents import MAX_DOCUMENT_SIZE, DocumentCipher
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
    api = build_app(access, store, cipher=DocumentCipher(b64encode(b"x" * 32).decode()))
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        async def call(method, path, role, status, *, org=None, json=None, data=None, headers=None, query=None):
            combined = {"Authorization": f"Bearer {role}", **(headers or {})}
            params = {"org_id": str(org)} if org else {}
            params.update(query or {})
            response = await client.request(method, f"/api/v1{path}", params=params, headers=combined,
                                            json=json, content=data)
            assert response.status_code == status, response.text
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

        docs = path + "/authorization-documents"
        pdf_headers = {"Content-Type": "application/pdf"}
        payload = b"%PDF-1.4\nPrivate signed authorization sample\n%%EOF"
        await call("POST", docs, "operator", 415, org=org, data=payload)
        await call("POST", docs, "operator", 413, org=org, headers=pdf_headers,
                   data=b"%PDF-" + b"x" * MAX_DOCUMENT_SIZE)
        assert (await call("POST", docs, "operator", 422, org=org, headers=pdf_headers,
                           data=b"not a PDF")).json()["code"] == "invalid_document"
        uploaded = (await call("POST", docs, "operator", 201, org=org, headers=pdf_headers, data=payload)).json()
        digest = sha256(payload).hexdigest()
        assert uploaded["digest"] == digest
        with admin.connect() as connection:
            ciphertext = connection.scalar(text("SELECT ciphertext FROM pentest_agent.authorization_document"))
            assert payload not in ciphertext
        download = docs + f"/{uploaded['id']}"
        await call("GET", download, "viewer", 404, org=org)
        await call("GET", download, "platform", 404, org=org)
        downloaded = await call("GET", download, "approver", 200, org=org)
        assert downloaded.content == payload
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
        saved_report = (await call("GET", plan_path + "/report", "viewer", 200, org=org)).content
        await call("POST", record + "/decisions", "approver", 409, org=org, json=decision)
        await call("POST", record + "/revisions", "operator", 409, org=org, json={**body, "previous_revision": 1})

        await call("POST", record + "/decisions", "approver", 200, org=org,
                   json={**decision, "decision": "revoke", "reason": "Mandate changed"})
        plan = (await call("GET", plan_path, "viewer", 200, org=org)).json()
        assert plan["status"] == "reviewed"
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
        await call("POST", path + "/targets", "operator", 409, org=org, json=target)
        await call("GET", record, "viewer", 200, org=org)


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
