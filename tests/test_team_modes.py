import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from domain.team_modes import TEAM_CATALOG, ArtifactKind, TeamId, TeamMode, ToolId, build_catalog


@pytest.mark.parametrize(("mode_id", "tool", "output"), [
    ("red", ToolId.CAPTURE_REVIEW, ArtifactKind.EXPOSURE_OBSERVATIONS),
    ("blue", ToolId.EVENT_REVIEW, ArtifactKind.TRIAGE_OBSERVATIONS),
    ("purple", ToolId.COVERAGE_COMPARISON, ArtifactKind.COVERAGE_MATRIX),
    ("yellow", ToolId.CODE_REVIEW, ArtifactKind.CODE_REVIEW_DRAFT),
    ("orange", ToolId.LEARNING_BRIEF, ArtifactKind.LEARNING_CARD),
    ("green", ToolId.REMEDIATION_COMPARISON, ArtifactKind.REMEDIATION_RECORD),
    ("white", ToolId.SCOPE_RECORD_REVIEW, ArtifactKind.SCOPE_MINUTES),
    ("black", ToolId.TABLETOP_SCENARIO, ArtifactKind.CONTINUITY_RECORD),
    ("gold", ToolId.RISK_SUMMARY, ArtifactKind.RISK_BRIEF),
])
def test_specialty_has_a_typed_offline_workflow(mode_id, tool, output):
    mode = TEAM_CATALOG[mode_id]
    assert mode.version == 1
    assert mode.input_kinds and mode.inputs
    assert mode.output_kind == output
    assert mode.workflow[0].tool == tool
    assert mode.execution_order() == (tool.value,)


def test_catalog_contains_all_modes_as_pending_metadata():
    assert set(TEAM_CATALOG) == set(TeamId)
    assert len(TEAM_CATALOG) == 10
    assert all(mode.status == "pending" for mode in TEAM_CATALOG.values())
    assert {mode.id for mode in TEAM_CATALOG.values() if mode.eligible_for_analysis} == {TeamId.WHITE, TeamId.BLUE}
    rainbow = TEAM_CATALOG[TeamId.RAINBOW]
    assert rainbow.execution_order() == (
        "white", "red", "blue", "yellow", "black", "purple", "orange", "green", "gold",
    )
    assert {step.team for step in rainbow.workflow} == set(TEAM_CATALOG) - {TeamId.RAINBOW}
    assert all(step.version == TEAM_CATALOG[step.team].version for step in rainbow.workflow)


def test_manifest_digest_uses_canonical_json():
    mode = TEAM_CATALOG[TeamId.RED]
    snapshot = mode.canonical_json()
    assert mode.digest == sha256(snapshot.encode("utf-8")).hexdigest()
    fields = json.loads(snapshot)
    assert TeamMode.model_validate(dict(reversed(list(fields.items())))).canonical_json() == snapshot
    assert TeamMode.model_validate({**fields, "version": 2}).digest != mode.digest


@pytest.mark.parametrize(("after", "message"), [
    (["not-a-stage"], "Unknown dependency"),
    (["gold"], "Dependency cycle"),
])
def test_catalog_rejects_invalid_dependency_graph(after, message):
    rainbow = TEAM_CATALOG[TeamId.RAINBOW].model_dump(mode="json")
    rainbow["workflow"][0]["after"] = after
    modes = tuple(mode for mode in TEAM_CATALOG.values() if mode.id != TeamId.RAINBOW)
    with pytest.raises(ValueError, match=message):
        build_catalog((*modes, TeamMode.model_validate(rainbow)))


def test_catalog_rejects_duplicate_modes_and_workflow_steps():
    red = TEAM_CATALOG[TeamId.RED]
    with pytest.raises(ValueError, match="Duplicate team mode"):
        build_catalog((*TEAM_CATALOG.values(), red))

    data = red.model_dump(mode="json")
    data["workflow"].append(data["workflow"][0])
    modes = tuple(mode for mode in TEAM_CATALOG.values() if mode.id != TeamId.RED)
    with pytest.raises(ValueError, match="Duplicate step"):
        build_catalog((*modes, TeamMode.model_validate(data)))


def test_catalog_rejects_unknown_or_unavailable_references():
    red = TEAM_CATALOG[TeamId.RED].model_dump(mode="json")
    red["workflow"][0]["tool"] = "unknown-tool"
    with pytest.raises(ValidationError, match="unknown-tool"):
        TeamMode.model_validate(red)

    rainbow = TEAM_CATALOG[TeamId.RAINBOW].model_dump(mode="json")
    rainbow["workflow"][0]["version"] = 99
    modes = tuple(mode for mode in TEAM_CATALOG.values() if mode.id != TeamId.RAINBOW)
    with pytest.raises(ValueError, match="unknown Rainbow specialty version"):
        build_catalog((*modes, TeamMode.model_validate(rainbow)))
