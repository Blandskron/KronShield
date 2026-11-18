from html import escape
from urllib.parse import parse_qsl, quote

import pytest

from core import sqli, xss
from core.probe_query import encode_probe_query
from domain.models import FindingConfidence, FindingStatus, FindingType


MARKER = "<script>void 0</script>"


@pytest.mark.parametrize("body", [
    escape(MARKER),
    quote(MARKER, safe=""),
    f"<!-- {MARKER} --> <script>void 1</script>",
    f'<textarea>{MARKER}</textarea>',
    f'<textarea/>{MARKER}',
    f'<template>{MARKER}</template>',
    f'<div title="{MARKER}">example</div>',
    '<script type="application/json" type="text/javascript">{"demo":1}</script>',
])
def test_literal_or_encoded_but_inert_reflection_stays_observed(body):
    marker = body if body.startswith('<script type="application/json"') else MARKER
    finding = xss.analyze(body, marker, baseline="clean", content_type="text/html")

    assert finding.type is FindingType.XSS
    assert finding.status is FindingStatus.OBSERVED
    assert finding.confidence is FindingConfidence.LOW
    assert finding.payload is None


@pytest.mark.parametrize("marker", [MARKER, "<svg onload='void 0'></svg>"])
def test_new_active_markup_in_a_captured_html_document_is_only_suspected(marker):
    body = f"<p>fixture</p>\n\n {marker}"
    finding = xss.analyze(body, marker, baseline="<p>fixture</p>", content_type="text/html; charset=utf-8")

    assert finding.status is FindingStatus.SUSPECTED
    assert finding.confidence is FindingConfidence.MEDIUM
    assert finding.payload is None


@pytest.mark.parametrize(
    ("baseline", "content_type"),
    [("clean", None), ("clean", "text/plain"), (None, "text/html"),
     (MARKER, "text/html"), (escape(MARKER), "text/html")],
)
def test_reflection_needs_known_html_and_a_clean_baseline_to_be_suspected(baseline, content_type):
    finding = xss.analyze(MARKER, MARKER, baseline=baseline, content_type=content_type)
    assert finding.status is FindingStatus.OBSERVED
    assert finding.confidence is FindingConfidence.LOW


def test_plain_marker_and_absent_marker_are_distinguished():
    assert xss.analyze("show marker", "marker", baseline="clean", content_type="text/html").status is FindingStatus.OBSERVED
    assert xss.analyze("clean", "marker", baseline="clean", content_type="text/html") is None


def test_generic_database_language_is_ignored():
    assert sqli.analyze("SQLite, MySQL and PostgreSQL syntax tutorial. Try SQL.", baseline="clean") is None


def test_static_database_error_does_not_become_suspected_after_minor_text_changes():
    finding = sqli.analyze("ERROR: syntax error at or near other", baseline="ERROR: syntax error at or near test")
    assert finding.status is FindingStatus.OBSERVED
    assert finding.confidence is FindingConfidence.LOW


@pytest.mark.parametrize(("probe", "signature"), [
    ("You have an error in your SQL syntax; check the manual", "mysql-syntax"),
    ("ERROR: syntax error at or near test", "postgres-syntax"),
    ("sqlite3.OperationalError: near &quot;test&quot;: syntax error", "sqlite-operational"),
    ("ORA-00933: SQL command not properly ended", "oracle-syntax"),
    ("Unclosed quotation mark after the character string", "sqlserver-quotation"),
])
def test_database_specific_error_needs_a_comparable_baseline_for_suspicion(probe, signature):
    assert sqli.analyze(probe).status is FindingStatus.OBSERVED
    finding = sqli.analyze(probe, baseline="Response without a database error.")
    assert finding.status is FindingStatus.SUSPECTED
    assert finding.confidence is FindingConfidence.MEDIUM
    assert finding.extra["signatures"] == [signature]
    assert finding.payload is None


def test_missing_probe_response_is_inconclusive_and_empty_body_is_valid():
    for finding in (xss.analyze(None, MARKER), sqli.analyze(None)):
        assert finding.type is FindingType.ERROR
        assert finding.status is FindingStatus.INCONCLUSIVE
        assert finding.confidence is None
    assert xss.analyze("", MARKER) is None
    assert sqli.analyze("") is None


def test_probe_query_preserves_existing_pairs_and_encodes_the_marker_as_one_value():
    original = parse_qsl("q=old&sort=&tag=a&tag=b", keep_blank_values=True)
    marker = "a&b=2 +# /á"
    query = encode_probe_query(original, "q", marker)

    assert parse_qsl(query, keep_blank_values=True) == [("q", marker), ("sort", ""), ("tag", "a"), ("tag", "b")]
    assert "%26b%3D2" in query and "%23" in query and "%C3%A1" in query
    assert encode_probe_query([("page", "1")], "q", "new") == "page=1&q=new"


def test_probe_query_rejects_an_ambiguous_parameter_without_changing_other_duplicates():
    with pytest.raises(ValueError, match="ambiguous"):
        encode_probe_query([("q", "first"), ("q", "second")], "q", "marker")
