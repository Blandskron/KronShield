"""Offline database-error heuristic for a previously captured HTTP body."""

from domain.models import Finding, FindingType


_SQL_ERROR_SIGNS = (
    "sql", "syntax", "mysql", "psql", "postgre", "sqlite",
    "odbc", "ora-", "warning: mysql", "unclosed quotation",
)


def analyze(body: str) -> Finding | None:
    if not any(sign in body.lower() for sign in _SQL_ERROR_SIGNS):
        return None
    return Finding(
        type=FindingType.SQLI,
        detail="Posible SQLi: se observó un indicador textual. Se requiere corroboración.",
    )
