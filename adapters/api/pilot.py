"""Loopback-only browser and CLI login for the Compose pilot."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import SecretStr, StringConstraints, field_validator

from adapters.api.auth import AUTH_HEADERS, RequestAuth
from adapters.api.contract import Output
from adapters.api.engagement_models import Contract
from application.access import AccessError
from infra.pilot_auth import TOKEN_SECONDS, PilotStore


class AuthMode(Output):
    mode: Literal["oidc", "pilot"]


class Credentials(Contract):
    username: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{2,31}$")]
    password: SecretStr

    @field_validator("password")
    @classmethod
    def password_length(cls, value):
        if not 12 <= len(value.get_secret_value()) <= 128:
            raise ValueError("Password must have between 12 and 128 characters")
        return value


class BootstrapInput(Credentials):
    code: Annotated[str, StringConstraints(min_length=32, max_length=128)]


class Account(Output):
    user_id: UUID


class Token(Output):
    access_token: str
    expires_in: int
    token_type: Literal["Bearer"] = "Bearer"


def pilot_routes(auth: RequestAuth, store: PilotStore | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def local(request: Request, *, browser: bool) -> PilotStore:
        if store is None:
            raise AccessError(404, "pilot_unavailable")
        origins = request.headers.getlist("origin")
        if (browser or origins) and origins != [auth.origin]:
            raise AccessError(403, "origin_denied")
        return store

    @router.get("/auth/mode", response_model=AuthMode)
    def mode() -> AuthMode:
        return AuthMode(mode="pilot" if store is not None else "oidc")

    @router.post("/bootstrap/redeem", status_code=201, response_model=Account)
    def bootstrap(request: Request, body: BootstrapInput) -> dict:
        return {"user_id": local(request, browser=True).enroll(
            body.username, body.password.get_secret_value(), bootstrap_code=body.code)}

    @router.post("/auth/local/accounts", status_code=201, response_model=Account)
    def accounts(request: Request, body: Credentials) -> dict:
        backend = local(request, browser=False)
        user = auth.identity(request)
        return {"user_id": backend.enroll(body.username, body.password.get_secret_value(), actor=user.user_id)}

    @router.post("/auth/local/login", response_model=Account)
    def login(request: Request, body: Credentials) -> JSONResponse:
        user_id = local(request, browser=True).authenticate(body.username, body.password.get_secret_value())
        token = auth.auth.issue_session(user_id, request.cookies.get(auth.session_cookie))
        response = JSONResponse({"user_id": str(user_id)}, headers=AUTH_HEADERS)
        response.set_cookie(auth.session_cookie, token, max_age=int(auth.auth.session_ttl.total_seconds()),
                            **auth.cookie_options)
        return response

    @router.post("/auth/local/token", response_model=Token)
    def token(request: Request, body: Credentials) -> Token:
        backend = local(request, browser=False)
        user_id = backend.authenticate(body.username, body.password.get_secret_value())
        return Token(access_token=backend.issue_token(user_id, body.username), expires_in=TOKEN_SECONDS)

    @router.post("/auth/local/revoke", status_code=204, response_class=Response)
    def revoke(request: Request) -> Response:
        backend = local(request, browser=False)
        identity = auth.identity(request)
        if identity.session is not None:
            raise AccessError(403, "cli_token_required")
        backend.revoke_token(request.headers["authorization"].partition(" ")[2])
        return Response(status_code=204, headers=AUTH_HEADERS)

    return router
