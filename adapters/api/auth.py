"""HTTP requests for browser sessions and revocable API bearer credentials."""

from dataclasses import dataclass, field
from hmac import compare_digest
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from adapters.api.contract import SessionInfo
from application.access import AccessError, Action
from application.authentication import Authentication, WebSession
from infra.auth_store import PostgresAuthStore
from infra.engagements import inventory_item, is_platform_admin, organization_role
from infra.tenancy import tenant_transaction

SESSION_COOKIE = "__Host-pentest-session"
LOGIN_COOKIE = "__Host-pentest-login"
AUTH_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
COOKIE_OPTIONS = {"path": "/", "secure": True, "httponly": True, "samesite": "lax"}


@dataclass(frozen=True)
class RequestIdentity:
    user_id: UUID
    session: WebSession | None = field(default=None, repr=False)


class RequestAuth:
    def __init__(self, auth: Authentication, origin: str, *, pilot: bool = False) -> None:
        self.auth = auth
        self.origin = origin
        self.pilot = pilot
        self.session_cookie = "pentest-pilot-session" if pilot else SESSION_COOKIE
        self.cookie_options = {**COOKIE_OPTIONS, "secure": not pilot}

    def identity(self, request: Request) -> RequestIdentity:
        headers = request.headers.getlist("authorization")
        token = request.cookies.get(self.session_cookie)
        if headers:
            scheme, _, bearer = headers[0].partition(" ")
            if len(headers) != 1 or token is not None or scheme.lower() != "bearer" or not bearer:
                raise AccessError(401, "invalid_credentials")
            return RequestIdentity(self.auth.bearer_user(bearer))
        if not token:
            raise AccessError(401, "authentication_required")
        session = self.auth.browser_session(token)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origins = request.headers.getlist("origin")
            csrf = request.headers.getlist("x-csrf-token")
            if (
                origins != [self.origin] or len(csrf) != 1 or not csrf[0].isascii()
                or not compare_digest(csrf[0], session.csrf)
            ):
                raise AccessError(403, "csrf_denied")
        return RequestIdentity(session.user_id, session)


def auth_routes(access: RequestAuth, store: PostgresAuthStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/auth/login", status_code=303, response_class=RedirectResponse)
    def login() -> RedirectResponse:
        if access.pilot:
            raise AccessError(404, "oidc_unavailable")
        url, browser = access.auth.start_login()
        response = RedirectResponse(url, status_code=303, headers=AUTH_HEADERS)
        response.set_cookie(LOGIN_COOKIE, browser, max_age=int(access.auth.login_ttl.total_seconds()),
                            **COOKIE_OPTIONS)
        return response

    @router.get("/auth/callback", status_code=303, response_class=RedirectResponse)
    def callback(request: Request, state: str = "", code: str = "") -> RedirectResponse:
        for name in ("state", "code"):
            if len(request.query_params.getlist(name)) != 1:
                raise AccessError(401, "invalid_login")
        token = access.auth.finish_login(state, code, request.cookies.get(LOGIN_COOKIE),
                                         request.cookies.get(access.session_cookie))
        response = RedirectResponse(f"{access.origin}/", status_code=303, headers=AUTH_HEADERS)
        response.set_cookie(SESSION_COOKIE, token, max_age=int(access.auth.session_ttl.total_seconds()),
                            **COOKIE_OPTIONS)
        response.delete_cookie(LOGIN_COOKIE, **COOKIE_OPTIONS)
        return response

    @router.post("/auth/logout", status_code=204, response_class=Response)
    def logout(request: Request) -> Response:
        identity = access.identity(request)
        if identity.session is None:
            raise AccessError(403, "browser_session_required")
        access.auth.logout(request.cookies[access.session_cookie])
        response = Response(status_code=204, headers=AUTH_HEADERS)
        response.delete_cookie(access.session_cookie, **access.cookie_options)
        return response

    @router.get("/me", response_model=SessionInfo)
    def me(request: Request, org_id: UUID | None = None, project_id: UUID | None = None) -> JSONResponse:
        identity = access.identity(request)
        payload = {"user_id": str(identity.user_id), "source": "web" if identity.session else "cli"}
        with tenant_transaction(store.engine, user_id=identity.user_id, org_id=None) as connection:
            payload["platform_admin"] = is_platform_admin(connection, identity.user_id)
        if identity.session:
            payload["csrf_token"] = identity.session.csrf
        if org_id is None and project_id is not None:
            raise AccessError(422, "project_context_required")
        if org_id is not None and project_id is None:
            with tenant_transaction(store.engine, user_id=identity.user_id, org_id=org_id) as connection:
                inventory_item(connection, "organization", org_id)
                payload.update(org_id=str(org_id), organization_role=organization_role(connection, identity.user_id, org_id))
        if org_id is not None and project_id is not None:
            with store.project(identity.user_id, org_id, project_id, Action.READ) as (_, project):
                payload.update(org_id=str(org_id), project_id=str(project_id),
                               organization_role=project.organization_role, project_role=project.project_role,
                               permissions=sorted(action.value for action in project.permissions))
        return JSONResponse(payload, headers=AUTH_HEADERS)

    return router
