"""Prepare audit plans without network access."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import NoReturn

from application.policy import ScopeDecision, evaluate_scope
from application.transport import SafeTransport
from core.recon import run_authorized
from core.scanner import scan_authorized_port
from domain.authorization import Authorization, ScopeTarget
from domain.budget import BudgetLimits
from domain.models import Finding


class ActiveAuditDisabled(RuntimeError):
    """The current release supports planning and offline analysis."""


class Profile(str, Enum):
    WEB_BASELINE = "web-baseline"
    TCP_BASELINE = "tcp-baseline"


@dataclass(frozen=True)
class AuditCheck:
    technique: str
    adapter: Callable[[ScopeTarget, SafeTransport], Finding | list[Finding]]


_CHECKS = MappingProxyType({
    Profile.WEB_BASELINE: AuditCheck("http-baseline", run_authorized),
    Profile.TCP_BASELINE: AuditCheck("tcp-connect", scan_authorized_port),
})


@dataclass(frozen=True)
class AuditPlan:
    profile: Profile
    technique: str
    target: ScopeTarget
    scope: ScopeDecision
    limits: BudgetLimits


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def prepare_plan(
    target: ScopeTarget,
    profile: Profile,
    limits: BudgetLimits,
    *,
    authorization: Authorization | None = None,
    organization_id: str = "",
    project_id: str = "",
    clock: Callable[[], datetime] = _utc_now,
) -> AuditPlan:
    """Evaluate the proposed operation against the supplied authorization revision."""
    if not isinstance(profile, Profile):
        raise ValueError("Perfil de auditoría desconocido.")
    if profile is Profile.WEB_BASELINE:
        if target.scheme is None or target.method not in {"GET", "HEAD"}:
            raise ValueError("El perfil web requiere un destino HTTP(S) y un método de lectura.")
    else:
        if target.port is None or target.path:
            raise ValueError("El perfil TCP requiere un puerto y una URL sin ruta de aplicación.")
        target = replace(target, scheme=None, path=None, method=None, trailing_slash=False)

    check = _CHECKS[profile]
    scope = evaluate_scope(
        authorization, target, organization_id=organization_id, project_id=project_id,
        technique=check.technique, clock=clock,
    )
    return AuditPlan(profile, check.technique, target, scope, limits)


def audit_website(url: str, api_key: str | None = None) -> NoReturn:
    """Retired entry point, kept to give existing callers a clear error."""
    raise ActiveAuditDisabled("La ejecución activa está deshabilitada. Usa audit plan o audit analyze.")
