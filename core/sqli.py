"""Compare specific database error signatures in saved HTTP bodies."""

import re
from html import unescape

from domain.models import Finding, FindingConfidence, FindingStatus, FindingType


_SIGNATURES = {
    "mysql-syntax": r"\byou have an error in your sql syntax\b",
    "postgres-syntax": r"\b(?:error:\s*syntax error at or near|unterminated quoted string at or near)\b",
    "sqlite-operational": r"\bsqlite3\.operationalerror:\s*(?:near\b[^\r\n]{1,160}:\s*syntax error|unrecognized token)",
    "oracle-syntax": r"\bORA-(?:00907|00933|00936|01756)\b",
    "sqlserver-quotation": r"\bunclosed quotation mark after the character string\b",
}
_PATTERNS = {signal: re.compile(pattern, re.IGNORECASE) for signal, pattern in _SIGNATURES.items()}


def _signals(body: str) -> set[str]:
    plain = unescape(body)
    return {signal for signal, pattern in _PATTERNS.items() if pattern.search(plain)}


def analyze(body: str | None, *, baseline: str | None = None) -> Finding | None:
    if body is None:
        return Finding(
            type=FindingType.ERROR, detail="Análisis SQLi inconcluso: falta la respuesta de prueba.",
            status=FindingStatus.INCONCLUSIVE,
        )
    signals = _signals(body)
    if not signals:
        return None

    if baseline is not None:
        new_signals = signals - _signals(baseline)
        if new_signals:
            return Finding(
                type=FindingType.SQLI, detail="Posible SQLi: firma de error de base de datos ausente en la respuesta base.",
                extra={"signatures": sorted(new_signals)},
                status=FindingStatus.SUSPECTED, confidence=FindingConfidence.MEDIUM,
            )

    detail = (
        "La firma de error de base de datos también aparece en la respuesta base."
        if baseline is not None else "Se observó una firma de error de base de datos sin una respuesta base para comparar."
    )
    return Finding(
        type=FindingType.SQLI, detail=detail, extra={"signatures": sorted(signals)},
        status=FindingStatus.OBSERVED, confidence=FindingConfidence.LOW,
    )
