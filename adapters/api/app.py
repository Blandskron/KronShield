"""Compose the API, probes and public contract."""

import os
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, event, make_url, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException

from adapters.api.auth import AUTH_HEADERS, SESSION_COOKIE, RequestAuth, auth_routes
from adapters.api.contract import API_VERSION, SCHEMA_REVISION, Health, Problem
from adapters.api.engagements import engagement_routes
from adapters.api.legacy import legacy_routes
from adapters.api.memberships import membership_routes
from adapters.api.oidc import OIDCProvider, OIDCSettings
from adapters.api.pilot import pilot_routes
from adapters.api.scope_reviews import scope_review_routes
from application.access import AccessError
from application.authentication import Authentication
from application.documents import DocumentCipher
from infra.auth_store import RUNTIME_ROLE_QUERY, PostgresAuthStore, UnsafeRuntimeRole
from infra.pilot_auth import PilotStore


ERROR_STATUSES = (400, 401, 403, 404, 409, 412, 413, 415, 422, 428, 503)


def build_app(access: RequestAuth, store: PostgresAuthStore, *, cipher: DocumentCipher | None = None,
              pilot: PilotStore | None = None, lifespan=None) -> FastAPI:
    api = FastAPI(title="BLANDSKRON Pentest Agent", version=API_VERSION, lifespan=lifespan,
                  openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", redoc_url=None,
                  responses={status: {"model": Problem, "description": HTTPStatus(status).phrase}
                             for status in ERROR_STATUSES})

    def problem(request, status, code, headers=None, errors=None):
        title = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "HTTP error"
        value = Problem(type=f"urn:pentest-agent:problem:{code}", title=title, status=status, code=code,
                        detail=title, request_id=request.state.request_id, errors=errors)
        return JSONResponse(value.model_dump(mode="json", exclude_none=True), status_code=status,
                            media_type="application/problem+json", headers={**AUTH_HEADERS, **(headers or {})})

    @api.exception_handler(AccessError)
    async def access_error(request: Request, error: AccessError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else {}
        return problem(request, error.status, error.code, headers=headers)

    @api.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        codes = {404: "route_not_found", 405: "method_not_allowed"}
        return problem(request, error.status_code, codes.get(error.status_code, "http_error"),
                       headers=error.headers)

    @api.exception_handler(SQLAlchemyError)
    @api.exception_handler(UnsafeRuntimeRole)
    async def database_error(request: Request, error: Exception) -> JSONResponse:
        return problem(request, 503, "database_unavailable")

    @api.exception_handler(IntegrityError)
    async def integrity_error(request: Request, error: IntegrityError) -> JSONResponse:
        if getattr(error.orig, "sqlstate", None) in {"23503", "23505"}:
            return problem(request, 409, "resource_conflict")
        return await database_error(request, error)

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [{"field": item["loc"], "type": item["type"]} for item in error.errors()]
        return problem(request, 422, "invalid_request", errors=details)

    @api.middleware("http")
    async def request_metadata(request: Request, call_next):
        request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    @api.get("/api/v1/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok")

    @api.get("/api/v1/ready", response_model=Health)
    def ready() -> Health:
        try:
            with store.engine.connect() as connection:
                revisions = connection.scalars(text("SELECT version_num FROM public.pentest_agent_alembic_version")).all()
        except (SQLAlchemyError, UnsafeRuntimeRole):
            raise AccessError(503, "database_unavailable") from None
        if revisions != [SCHEMA_REVISION]:
            raise AccessError(503, "schema_not_ready")
        return Health(status="ready")

    api.state.request_auth = access
    api.state.auth_store = store
    api.include_router(auth_routes(access, store))
    api.include_router(pilot_routes(access, pilot))
    api.include_router(membership_routes(access, store))
    if cipher is not None:
        api.include_router(engagement_routes(access, store, cipher))
        api.include_router(scope_review_routes(access, store))
        api.include_router(legacy_routes(access, store))

    original_openapi = api.openapi

    def openapi():
        schema = original_openapi()
        schema["components"]["securitySchemes"] = {
            "bearer": {"type": "http", "scheme": "bearer"},
            "session": {"type": "apiKey", "in": "cookie", "name": SESSION_COOKIE},
            "pilotSession": {"type": "apiKey", "in": "cookie", "name": "pentest-pilot-session"},
        }
        schema["security"] = [{"bearer": []}, {"session": []}, {"pilotSession": []}]
        for path, operations in schema["paths"].items():
            for operation in operations.values():
                if path in {
                    "/api/v1/health", "/api/v1/ready", "/api/v1/auth/login", "/api/v1/auth/callback",
                    "/api/v1/auth/mode", "/api/v1/bootstrap/redeem", "/api/v1/auth/local/login", "/api/v1/auth/local/token",
                }:
                    operation["security"] = []
                elif path == "/api/v1/auth/logout":
                    operation["security"] = [{"session": []}, {"pilotSession": []}]
                for status, response in operation["responses"].items():
                    if status in {str(code) for code in ERROR_STATUSES} and "content" in response:
                        content = response["content"]
                        if "application/json" in content:
                            content["application/problem+json"] = content.pop("application/json")
        return schema

    api.openapi = openapi
    return api


def _oidc_settings(origin: str) -> OIDCSettings:
    return OIDCSettings(
        issuer=os.environ["PENTEST_AGENT_OIDC_ISSUER"],
        authorize_url=os.environ["PENTEST_AGENT_OIDC_AUTHORIZE_URL"],
        token_url=os.environ["PENTEST_AGENT_OIDC_TOKEN_URL"],
        jwks_url=os.environ["PENTEST_AGENT_OIDC_JWKS_URL"],
        introspection_url=os.environ["PENTEST_AGENT_OIDC_INTROSPECTION_URL"],
        client_id=os.environ["PENTEST_AGENT_OIDC_CLIENT_ID"],
        client_secret=os.environ["PENTEST_AGENT_OIDC_CLIENT_SECRET"],
        api_audience=os.environ["PENTEST_AGENT_OIDC_API_AUDIENCE"],
        api_scope=os.environ["PENTEST_AGENT_OIDC_API_SCOPE"],
        web_origin=origin,
    )


def create_app() -> FastAPI:
    mode = os.getenv("PENTEST_AGENT_AUTH_MODE", "oidc")
    origin = os.environ["PENTEST_AGENT_WEB_ORIGIN"]
    if mode == "pilot":
        address = urlsplit(origin)
        if (address.scheme != "http" or address.hostname not in {"localhost", "127.0.0.1"}
                or address.username is not None or address.path or address.query or address.fragment):
            raise ValueError("Pilot mode requires an HTTP loopback origin")
        files = Path(os.environ["PENTEST_AGENT_PILOT_FILES"])
        url = URL.create("postgresql+psycopg", username="pentest_login", host="postgres",
                         database="pentest", password=(files / "runtime").read_text().strip())
        cipher = DocumentCipher((files / "document-key").read_text().strip())
    elif mode == "oidc":
        settings = _oidc_settings(origin)
        url = make_url(os.environ["PENTEST_AGENT_RUNTIME_URL"])
        if url.drivername != "postgresql+psycopg":
            raise ValueError("PENTEST_AGENT_RUNTIME_URL must use postgresql+psycopg")
        cipher = DocumentCipher(os.environ["PENTEST_AGENT_DOCUMENT_KEY"])
    else:
        raise ValueError("Unknown authentication mode")

    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    client = httpx.Client(timeout=5, trust_env=False, follow_redirects=False)
    store = PostgresAuthStore(engine)
    pilot = PilotStore(engine, (files / "bootstrap").read_text().strip()) if mode == "pilot" else None
    provider = pilot if pilot is not None else OIDCProvider(settings, client)
    access = RequestAuth(Authentication(provider, store), origin, pilot=pilot is not None)


    @event.listens_for(engine, "connect")
    def validate_database_role(dbapi_connection, _):
        with dbapi_connection.cursor() as cursor:
            cursor.execute(RUNTIME_ROLE_QUERY)
            allowed = cursor.fetchone()[0]
        dbapi_connection.rollback()
        if not allowed:
            raise UnsafeRuntimeRole("Use a non-owner database login granted pentest_agent_runtime")

    @asynccontextmanager
    async def resources(_):
        try:
            yield
        finally:
            client.close()
            engine.dispose()

    api = build_app(access, store, cipher=cipher, pilot=pilot, lifespan=resources)
    web_dist = os.getenv("PENTEST_AGENT_WEB_DIST")
    if web_dist:
        api.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return api
