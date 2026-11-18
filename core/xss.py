"""Offline reflection check for a previously captured HTTP body."""

from domain.models import Finding, FindingType


def analyze(body: str, marker: str) -> Finding | None:
    if not marker or not marker.strip() or len(marker) > 4096:
        raise ValueError("El marcador debe contener entre 1 y 4096 caracteres y no puede estar en blanco.")
    if marker not in body:
        return None
    return Finding(
        type=FindingType.XSS,
        detail="Posible XSS: marcador reflejado. La reflexión por sí sola no demuestra ejecución.",
    )
