"""Classify reflections in saved responses without executing browser content."""

import re
from bisect import bisect_right
from html import unescape
from html.parser import HTMLParser
from urllib.parse import unquote

from domain.models import Finding, FindingConfidence, FindingStatus, FindingType


_INERT = {"iframe", "noembed", "noframes", "noscript", "plaintext", "style", "template", "textarea", "title", "xmp"}
_SCRIPT_TYPES = {"", "module", "text/javascript", "application/javascript", "text/ecmascript", "application/ecmascript"}
_EVENTS = {"onload", "onerror", "onclick", "onfocus", "onmouseover", "onanimationstart"}


class _ReflectedMarkup(HTMLParser):
    def __init__(self, body: str, marker: str):
        super().__init__(convert_charrefs=False)
        self._lines = [0, *(match.end() for match in re.finditer("\n", body))]
        self._occurrences = [match.start() for match in re.finditer(re.escape(marker), body)]
        self._marker_length = len(marker)
        self._inert: list[str] = []
        self.active_markup = False

    def handle_starttag(self, tag, attrs):
        if self._inert or tag in _INERT:
            if tag in _INERT:
                self._inert.append(tag)
            return
        line, column = self.getpos()
        position = self._lines[line - 1] + column
        index = bisect_right(self._occurrences, position) - 1
        if index < 0 or position + len(self.get_starttag_text()) > self._occurrences[index] + self._marker_length:
            return
        if tag == "script":
            script_type = next((value or "" for name, value in attrs if name == "type"), "")
            self.active_markup |= script_type.split(";", 1)[0].strip().lower() in _SCRIPT_TYPES
        elif any(name in _EVENTS and value and value.strip() for name, value in attrs):
            self.active_markup = True

    def handle_startendtag(self, tag, attrs):
        # Slash syntax does not close inert HTML elements such as textarea.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self._inert and self._inert[-1] == tag and tag != "plaintext":
            self._inert.pop()


def _reflection(body: str, marker: str) -> str | None:
    if marker in body:
        return "literal"
    if marker in unescape(body) or marker in unquote(body):
        return "encoded"
    return None


def analyze(
    body: str | None, marker: str, *, baseline: str | None = None, content_type: str | None = None,
) -> Finding | None:
    if not marker or not marker.strip() or len(marker) > 4096:
        raise ValueError("El marcador debe contener entre 1 y 4096 caracteres y no puede estar en blanco.")
    if body is None:
        return Finding(
            type=FindingType.ERROR, detail="Análisis XSS inconcluso: falta la respuesta de prueba.",
            status=FindingStatus.INCONCLUSIVE,
        )
    reflection = _reflection(body, marker)
    if reflection is None:
        return None

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if (
        reflection == "literal" and "<" in marker and ">" in marker and media_type == "text/html"
        and baseline is not None and _reflection(baseline, marker) is None
    ):
        parser = _ReflectedMarkup(body, marker)
        try:
            parser.feed(body)
            parser.close()
        except (AssertionError, ValueError):
            pass
        else:
            if parser.active_markup:
                return Finding(
                    type=FindingType.XSS, detail="Posible XSS: marcado activo reflejado y ausente en la respuesta base.",
                    status=FindingStatus.SUSPECTED, confidence=FindingConfidence.MEDIUM,
                )

    detail = "Se observó un reflejo codificado del marcador." if reflection == "encoded" else (
        "Se observó un reflejo literal del marcador."
    )
    return Finding(
        type=FindingType.XSS, detail=f"{detail} La captura no demuestra ejecución.",
        status=FindingStatus.OBSERVED, confidence=FindingConfidence.LOW,
    )
