import json
from base64 import b64encode
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from application import evidence
from application.access import AccessError, authorize_project, Action
from application.documents import DocumentCipher
from domain.team_modes import TEAM_CATALOG, TeamId


@pytest.fixture
def setup():
    path = Path(__file__).with_name("fixtures") / "scope-review-v1.json"
    plan = json.loads(path.read_text(encoding="utf-8"))["plan"]
    actor, reviewer = UUID(plan["actor_id"]), UUID(plan["authorization"]["verifier_id"])
    org, project = UUID(plan["org_id"]), UUID(plan["project_id"])
    caller = authorize_project(org, project, actor, ("member", "operator"), Action.REQUEST_EVIDENCE)
    target = plan["targets"][0]["id"]
    payload = json.dumps({"target_id": target, "observations": [{"control": "logging", "result": "observed"}]}).encode()
    source = {"target_id": target, "digest": sha256(payload).hexdigest(), "size_bytes": len(payload),
              "kind": "control-observations-v1", "classification": "internal", "capability": "capture-review"}
    mode = TEAM_CATALOG[TeamId.RED]
    spec = {"plan_id": plan["id"], "plan_hash": plan["hash"], "mode_id": mode.id, "mode_version": mode.version,
            "mode_digest": mode.digest, "valid_from": plan["authorization"]["valid_from"],
            "valid_until": plan["authorization"]["valid_until"], "sources": [source]}
    request = {"requester": actor, "approver": reviewer, "status": "approved", "purpose": "offline-review",
               "digest": source["digest"], "now": datetime(2026, 1, 1, 12, tzinfo=timezone.utc)}
    return spec, plan, caller, request, payload


@pytest.mark.parametrize("mode", list(TEAM_CATALOG.values()), ids=lambda mode: mode.id.value)
def test_same_authorization_policy_for_every_mode(setup, mode):
    spec, plan, caller, args, _ = setup
    spec.update(mode_id=mode.id, mode_version=mode.version, mode_digest=mode.digest)
    if mode.id != TeamId.RAINBOW:
        spec["sources"][0]["capability"] = mode.workflow[0].tool
    parsed = evidence.PermissionSpec.model_validate(spec)
    assert evidence.authorize_use(parsed, plan, caller, **args) == parsed.sources[0]


@pytest.mark.parametrize(("condition", "code"), [
    ("actor", "evidence_not_found"), ("digest", "evidence_not_found"), ("expired", "evidence_permission_inactive"),
    ("revoked", "evidence_permission_inactive"), ("purpose", "evidence_purpose_denied"),
    ("third-party", "evidence_asset_not_allowed"), ("blocked", "evidence_plan_mismatch"),
    ("other-project", "plan_not_found"), ("capability", "evidence_capability_not_allowed"),
    ("mode", "evidence_mode_changed"),
])
def test_evidence_denial_matrix(setup, condition, code):
    spec, plan, caller, args, _ = setup
    if condition == "actor":
        args["requester"] = uuid4()
    elif condition == "digest":
        args["digest"] = "e" * 64
    elif condition == "expired":
        args["now"] = datetime.fromisoformat(spec["valid_until"])
    elif condition == "revoked":
        args["status"] = "revoked"
    elif condition == "purpose":
        args["purpose"] = "local-inference"
    elif condition == "third-party":
        plan["targets"][0]["attribution"] = "third_party"
    elif condition == "blocked":
        plan["status"] = "blocked"
    elif condition == "other-project":
        plan["project_id"] = str(uuid4())
    elif condition == "capability":
        spec["sources"][0]["capability"] = "event-review"
    else:
        spec["mode_version"] = 99
    with pytest.raises(AccessError) as denied:
        evidence.authorize_use(evidence.PermissionSpec.model_validate(spec), plan, caller, **args)
    assert denied.value.code == code


def test_restricted_classification_and_distinct_approver(setup):
    spec, _, caller, _, _ = setup
    spec["sources"][0]["classification"] = "restricted"
    spec["allow_local_inference"] = True
    with pytest.raises(ValidationError):
        evidence.PermissionSpec.model_validate(spec)
    approver = authorize_project(caller.org_id, caller.project_id, caller.user_id,
                                 ("member", "approver"), Action.DECIDE_EVIDENCE)
    with pytest.raises(AccessError, match="approval_requires_distinct_actor"):
        evidence.check_decider(approver, caller.user_id)


def test_retention_deadline_is_half_open_and_can_be_shorter_than_the_permission(setup):
    spec, plan, caller, args, _ = setup
    deadline = args["now"]
    spec["sources"][0]["retain_until"] = deadline
    parsed = evidence.PermissionSpec.model_validate(spec)
    assert evidence.retention_deadline(parsed, parsed.sources[0]) == deadline
    assert evidence.authorize_use(parsed, plan, caller, **{**args, "now": deadline - timedelta(microseconds=1)})
    with pytest.raises(AccessError, match="evidence_retention_elapsed"):
        evidence.authorize_use(parsed, plan, caller, **args)
    with pytest.raises(AccessError, match="evidence_retention_elapsed"):
        evidence.authorize_use(parsed, plan, caller, **{**args, "purpose": "local-inference"})


@pytest.mark.parametrize(("classification", "days"), [("internal", 30), ("restricted", 7)])
def test_classification_caps_retention(setup, classification, days):
    spec, _, _, _, _ = setup
    spec["valid_until"] = datetime.fromisoformat(spec["valid_from"]) + timedelta(days=60)
    spec["sources"][0]["classification"] = classification
    parsed = evidence.PermissionSpec.model_validate(spec)
    assert evidence.retention_deadline(parsed, parsed.sources[0]) == parsed.valid_from + timedelta(days=days)


def test_projection_excludes_source_text_and_checks_digest_and_size(setup):
    spec, plan, _, _, payload = setup
    parsed = evidence.PermissionSpec.model_validate(spec).sources[0]
    assert evidence.project_upload(parsed, payload) == json.loads(payload)
    for invalid in (payload + b" ", payload.replace(b"logging", b"secrets")):
        with pytest.raises(AccessError, match="evidence_source_mismatch"):
            evidence.project_upload(parsed, invalid)
    raw = json.dumps({**json.loads(payload), "headers": {"Authorization": "synthetic token"}}).encode()
    malformed = {**spec["sources"][0], "digest": sha256(raw).hexdigest(), "size_bytes": len(raw)}
    with pytest.raises(AccessError, match="invalid_evidence_source"):
        evidence.project_upload(evidence.Source.model_validate(malformed), raw)
    snapshot = deepcopy(plan)
    snapshot["targets"][0]["canonical_address"] += "?secret=fixture"
    snapshot["authorization"]["document_evidence_id"] = "private-document-reference"
    scope = evidence.project_plan(snapshot, parsed)
    assert not {"canonical_address", "authorization", "document_evidence_id"}.intersection(scope)
    assert "secret" not in json.dumps(scope) and "private-document-reference" not in json.dumps(scope)
    legacy_id = uuid4()
    legacy = evidence.Source.model_validate({**spec["sources"][0], "kind": "legacy-reference-v1",
                                            "legacy_id": legacy_id, "size_bytes": None})
    record = {"id": legacy_id, "source_digest": legacy.digest, "finding_count": 7, "detail": "private free text"}
    assert evidence.project_legacy(legacy, record) == {
        "id": str(legacy_id), "target_id": str(legacy.target_id), "origin": "legacy",
        "confidence": "unverified", "finding_count": 7,
    }


def event_batch_source(target, **changes):
    batch = {
        "target_id": target,
        "producer": "identity-audit",
        "window_start": "2026-01-01T11:00:00-03:00",
        "window_end": "2026-01-01T12:00:00-03:00",
        "events": [{"event_id": str(uuid4()), "occurred_at": "2026-01-01T11:10:00-03:00", "kind": "login-failure"}],
        **changes,
    }
    payload = json.dumps(batch).encode()
    source = evidence.Source(kind="event-batch-v1", capability="event-review", target_id=target,
                             digest=sha256(payload).hexdigest(), size_bytes=len(payload), classification="internal")
    return source, payload


def test_event_projection_orders_events_by_utc_then_id(setup):
    spec, _, _, _, _ = setup
    target = spec["sources"][0]["target_id"]
    first, second, third = sorted(str(uuid4()) for _ in range(3))
    events = [
        {"event_id": third, "occurred_at": "2026-01-01T10:45:00-04:00", "kind": "login-success"},
        {"event_id": second, "occurred_at": "2026-01-01T11:10:00-03:00", "kind": "login-failure"},
        {"event_id": first, "occurred_at": "2026-01-01T14:10:00Z", "kind": "privilege-change"},
    ]
    source, payload = event_batch_source(target, events=events)
    projection = evidence.project_upload(source, payload)
    reverse_source, reverse_payload = event_batch_source(target, events=list(reversed(events)))
    assert evidence.project_upload(reverse_source, reverse_payload) == projection
    assert projection["producer"] == "identity-audit"
    assert projection["window_start"] == "2026-01-01T14:00:00Z"
    assert projection["window_end"] == "2026-01-01T15:00:00Z"
    assert [event["event_id"] for event in projection["events"]] == [first, second, third]
    assert [event["occurred_at"] for event in projection["events"]] == ["2026-01-01T14:10:00Z"] * 2 + [
        "2026-01-01T14:45:00Z"]
    empty, raw = event_batch_source(target, events=[])
    assert evidence.project_upload(empty, raw)["events"] == []


@pytest.mark.parametrize("timestamp", ["invalid", "2026-01-01T14:10:00", 1767276600,
                                       "2026-01-01T15:00:00Z", "0001-01-01T00:00:00+01:00"])
def test_events_reject_invalid_or_outside_timestamps(setup, timestamp):
    spec, _, _, _, _ = setup
    source, raw = event_batch_source(spec["sources"][0]["target_id"], events=[
        {"event_id": str(uuid4()), "occurred_at": timestamp, "kind": "login-failure"},
    ])
    with pytest.raises(AccessError, match="invalid_evidence_source"):
        evidence.project_upload(source, raw)


def test_event_batch_rejects_ambiguous_excess_and_mismatched_data(setup):
    spec, plan, caller, _, _ = setup
    target = spec["sources"][0]["target_id"]
    source, raw = event_batch_source(target)
    first_event = json.loads(raw)["events"][0]
    for changes in ({"events": [first_event] * 2}, {"events": [first_event] * 2001},
                    {"events": [{**first_event, "message": "unfiltered log"}]},
                    {"producer": "https://example.test/untrusted"},
                    {"window_end": "2026-01-01T14:00:00Z"}):
        invalid_source, invalid_raw = event_batch_source(target, **changes)
        with pytest.raises(AccessError, match="invalid_evidence_source"):
            evidence.project_upload(invalid_source, invalid_raw)
    with pytest.raises(AccessError, match="evidence_source_mismatch"):
        evidence.project_upload(source, raw + b" ")
    with pytest.raises(AccessError, match="evidence_asset_not_allowed"):
        evidence.project_upload(source.model_copy(update={"target_id": uuid4()}), raw)
    with pytest.raises(ValidationError):
        evidence.Source.model_validate({**source.model_dump(mode="json"), "capability": "scope-record-review"})
    mode = TEAM_CATALOG[TeamId.BLUE]
    spec.update(mode_id=mode.id, mode_version=mode.version, mode_digest=mode.digest, sources=[source])
    evidence.check_plan(evidence.PermissionSpec.model_validate(spec), plan, caller)
    spec["sources"] = [source.model_copy(update={"target_id": uuid4()})]
    with pytest.raises(AccessError, match="evidence_asset_not_allowed"):
        evidence.check_plan(evidence.PermissionSpec.model_validate(spec), plan, caller)


def test_cipher_binds_evidence_to_tenant_project_permission_and_id():
    cipher = DocumentCipher(b64encode(bytes(32)).decode())
    scope = (uuid4(), uuid4(), uuid4(), uuid4(), 1, "a" * 64)
    nonce, ciphertext = cipher.encrypt_evidence(*scope, b"data")
    assert cipher.decrypt_evidence(*scope, nonce, ciphertext) == b"data"
    for field in range(4):
        wrong = (*scope[:field], uuid4(), *scope[field + 1:])
        with pytest.raises(AccessError, match="evidence_unavailable"):
            cipher.decrypt_evidence(*wrong, nonce, ciphertext)
