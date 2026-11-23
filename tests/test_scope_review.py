from datetime import datetime, timedelta, timezone
from uuid import uuid4

from application.scope_review import fingerprint, review


def test_scope_review_denies_excluded_targets_and_expired_authorizations():
    org, project, authorization_id, assessment_id = (str(uuid4()) for _ in range(4))
    selected = {"authorization_id": authorization_id, "assessment_id": assessment_id}
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    active = {
        "revision": 1, "status": "approved", "delegator_id": uuid4(), "verifier_id": uuid4(),
        "document_evidence_id": uuid4(), "document_digest": "a" * 64, "limits": {},
        "valid_from": now, "valid_until": now + timedelta(hours=1), "environment": "lab",
        "scope_rules": [
            {"effect": "allow", "kind": "fqdn", "destination": "example.net"},
            {"effect": "deny", "kind": "application", "destination": "example.net",
             "scheme": "https", "ports": [443], "path_prefix": ["private"]},
        ],
    }
    target = {
        "id": uuid4(), "canonical_address": "https://example.net/private/", "version": 1,
        "environment": "lab", "attribution": "first_party", "third_party_id": None,
    }
    state = {"state": "active", "version": 1, "kill_switch": False}

    result = review(org, project, state, selected, active, 1, [target], now)
    assert result["status"] == "blocked"
    assert result["denials"] == ["excluded"]
    assert result["targets"][0]["rule_id"] == "2"

    expired = review(org, project, state, selected, active, 2, [target], active["valid_until"])
    assert expired["denials"] == ["authorization_superseded", "expired"]
    assert expired["execution"] == "disabled"


def test_snapshot_fingerprint_is_independent_of_key_order():
    first = {"id": "documento", "detail": {"b": 2, "a": 1}}
    second = {"detail": {"a": 1, "b": 2}, "id": "documento"}
    assert fingerprint(first) == fingerprint(second)
    second["detail"]["a"] = 2
    assert fingerprint(first) != fingerprint(second)


def test_scope_review_html_escapes_text_and_is_reproducible():
    from reports.report_html import render_scope_review_report

    review_id = str(uuid4())
    hostile = "<script>not an executable document field</script>"
    snapshot = {"id": review_id, "org_id": str(uuid4()), "project_id": str(uuid4()), "hash": "a" * 64,
                "status": "blocked", "checked_at": "2026-01-01T00:00:00+00:00",
                "denials": [hostile],
                "authorization": {"id": str(uuid4()), "revision": 2, "status": "draft",
                                  "valid_from": "2026-01-01", "valid_until": "2026-01-02",
                                  "document_digest": "b" * 64},
                "targets": [{"canonical_address": hostile, "environment": "lab", "version": 1,
                             "reason": "not_approved", "rule_id": None}]}
    rendered = render_scope_review_report(snapshot, hostile)
    assert rendered == render_scope_review_report(snapshot, hostile)
    assert hostile not in rendered and rendered.count("&lt;script&gt;") == 3
    assert "default-src 'none'" in rendered
    assert review_id in rendered and "a" * 64 in rendered
