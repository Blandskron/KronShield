import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from adapters.api.contract import Plan
from application.access import AccessError
from application.scope_review import fingerprint, review
from infra import scope_reviews
from reports.report_html import render_scope_review_report


@pytest.mark.parametrize("change", ["revoked", "expired"])
def test_historical_v1_plan_remains_readable_when_verification_becomes_stale(change, monkeypatch):
    fixture_path = Path(__file__).with_name("fixtures") / "scope-review-v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected = fixture["plan"]
    # Read fixtures in universal newline mode so a CRLF checkout keeps the same reference bytes.
    expected_html = fixture_path.with_suffix(".html").read_text(encoding="utf-8").encode("utf-8")
    stored = {**expected, "checked_at": datetime.fromisoformat(expected["checked_at"].replace("Z", "+00:00"))}
    mandate = expected["authorization"]
    # The API serializes UTC datetimes as Z. The snapshot hash covers +00:00 timestamps.
    public_plan = {**expected, "authorization": {
        **mandate, "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2026-01-02T00:00:00Z",
    }}
    record = {
        **mandate,
        "delegator_id": expected["actor_id"],
        "environment": "lab",
        "valid_from": datetime.fromisoformat(mandate["valid_from"]),
        "valid_until": datetime.fromisoformat(mandate["valid_until"]),
    }
    state = {"state": "active", "version": expected["project_version"], "kill_switch": False}
    clock = stored["checked_at"]

    def current_review(_connection, _caller, selection):
        result = review(expected["org_id"], expected["project_id"], state, selection,
                        record, mandate["latest_revision"], expected["targets"], clock)
        return result, clock

    monkeypatch.setattr(scope_reviews, "_current_review", current_review)
    plan_id = UUID(expected["id"])
    columns = {key: stored[key] for key in ("id", "actor_id", "hash", "checked_at")}
    row = {**columns, "snapshot": {key: value for key, value in stored.items() if key not in columns}}
    monkeypatch.setattr(scope_reviews, "_matching_row", lambda *_args: row)

    def assert_history():
        plan = scope_reviews.plan(None, plan_id)
        assert Plan.model_validate(plan).model_dump(mode="json") == public_plan
        plan["checked_at"] = plan["checked_at"].isoformat()
        assert render_scope_review_report(plan, fixture["label"]).encode("utf-8") == expected_html

    assert_history()
    assert scope_reviews.verify_plan(None, None, plan_id, expected["hash"]) == {
        "id": plan_id, "hash": expected["hash"], "status": "verified", "execution": "disabled",
    }

    if change == "revoked":
        record["status"] = "revoked"
    else:
        clock = record["valid_until"]

    with pytest.raises(AccessError) as stale:
        scope_reviews.verify_plan(None, None, plan_id, expected["hash"])
    assert (stale.value.status, stale.value.code) == (409, "plan_state_changed")
    assert_history()


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
