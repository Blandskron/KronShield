"""Evaluate a stored scope revision against inventory without network access."""

import json
from datetime import datetime, timezone
from hashlib import sha256
from ipaddress import ip_address, ip_network

from application.policy import evaluate_scope
from domain.authorization import Attribution, Authorization, AuthorizationStatus, RuleEffect, ScopeRule, ScopeTarget
from domain.targets import canonical_host, canonical_http_target


# The policy engine expects a named operation. This name only identifies inventory review.
REVIEW_OPERATION = "scope-review"


def canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fingerprint(value: dict) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _scope_rule(index: int, value: dict) -> ScopeRule:
    address = value["destination"]
    if value["kind"] == "cidr":
        address = ip_network(address)
    elif value["kind"] == "ip":
        address = ip_address(address)
    elif value["kind"] == "application":
        address = canonical_host(address)
    return ScopeRule(
        id=str(index), effect=RuleEffect(value["effect"]), destination=address,
        subdomains=value["kind"] == "subdomain", scheme=value.get("scheme"),
        ports=frozenset(value.get("ports") or ()), path_prefix=value.get("path_prefix"),
    )


def _target(value: dict) -> ScopeTarget:
    address = value["canonical_address"]
    attributes = {"environment": value["environment"], "attribution": Attribution(value["attribution"]),
                  "third_party_id": value["third_party_id"]}
    if "://" in address:
        return canonical_http_target(address, **attributes)
    return ScopeTarget(host=canonical_host(address), **attributes)


def review(
    organization_id: str, project_id: str, project_state: dict, selection: dict, record: dict,
    latest_revision: int, targets: list[dict], now: datetime,
) -> dict:
    authorization = Authorization(
        id=selection["authorization_id"], revision=record["revision"],
        organization_id=organization_id, project_id=project_id,
        delegator_id=str(record["delegator_id"]), document_reference=str(record["document_evidence_id"]),
        document_sha256=record["document_digest"], status=AuthorizationStatus(record["status"]),
        valid_from=record["valid_from"], valid_until=record["valid_until"], environment=record["environment"],
        techniques=frozenset({REVIEW_OPERATION}),
        rules=tuple(_scope_rule(index, rule) for index, rule in enumerate(record["scope_rules"], start=1)),
        verified_by=str(record["verifier_id"]) if record["verifier_id"] else None,
    )

    general_denials = []
    if project_state["state"] != "active":
        general_denials.append("project_archived")
    if project_state["kill_switch"]:
        general_denials.append("organization_kill_switch")
    if authorization.revision != latest_revision:
        general_denials.append("authorization_superseded")
    if not record["document_evidence_id"]:
        general_denials.append("authorization_document_missing")

    evaluated = []
    for item in targets:
        try:
            target = _target(item)
        except ValueError:
            reason, rule_id = "invalid_inventory_target", None
        else:
            decision = evaluate_scope(
                authorization, target, organization_id=organization_id, project_id=project_id,
                technique=REVIEW_OPERATION, clock=lambda: now,
            )
            reason, rule_id = decision.reason.value, decision.rule_id
        evaluated.append({
            **{key: item[key] for key in (
                "version", "canonical_address", "environment", "attribution", "third_party_id",
            )},
            "id": str(item["id"]), "reason": reason, "rule_id": rule_id,
        })

    denials = general_denials + sorted({item["reason"] for item in evaluated if item["reason"] != "allowed"})
    return {
        "schema_version": 1,
        "mode": "dry-run",
        "profile_id": REVIEW_OPERATION,
        "execution": "disabled",
        "org_id": organization_id,
        "project_id": project_id,
        "project_version": project_state["version"],
        "assessment_id": selection["assessment_id"],
        "status": "blocked" if denials else "reviewed",
        "denials": denials,
        "authorization": {
            "id": authorization.id, "revision": authorization.revision, "latest_revision": latest_revision,
            "status": authorization.status.value, "document_digest": authorization.document_sha256,
            "document_evidence_id": str(record["document_evidence_id"]) if record["document_evidence_id"] else None,
            "valid_from": authorization.valid_from.astimezone(timezone.utc).isoformat(),
            "valid_until": authorization.valid_until.astimezone(timezone.utc).isoformat(),
            "verifier_id": authorization.verified_by,
            "scope_rules": record["scope_rules"], "limits": record["limits"],
        },
        "targets": evaluated,
    }
