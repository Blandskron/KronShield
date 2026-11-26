import subprocess
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from application.access import AccessError
from application.analyses import AnalysisDraft, CoverageScenario
from application.analysis_dispatch import OfflineInput, StepOutput, StepWork, coverage_review, dispatch_step, event_review, next_tool
from domain.team_modes import TEAM_CATALOG, TeamId, ToolId


def test_frozen_rainbow_only_admits_the_next_step():
    rainbow = TEAM_CATALOG[TeamId.RAINBOW]
    snapshot = {"manifest": rainbow.model_dump(mode="json"), "manifest_digest": rainbow.digest,
                "stage_manifests": {step.id: TEAM_CATALOG[step.team].model_dump(mode="json") for step in rainbow.workflow}}
    assert next_tool(snapshot, set(), "white") == ToolId.SCOPE_RECORD_REVIEW
    assert next_tool(snapshot, {"white"}, "red") == ToolId.CAPTURE_REVIEW
    with pytest.raises(AccessError, match="analysis_transition_invalid"):
        next_tool(snapshot, set(), "red")
    with pytest.raises(AccessError, match="unknown_analysis_step"):
        next_tool(snapshot, set(), "other")
    snapshot["stage_manifests"]["white"]["version"] = 99
    with pytest.raises(AccessError, match="analysis_manifest_changed"):
        next_tool(snapshot, set(), "white")


@pytest.fixture
def inputs():
    target = uuid4()
    return (OfflineInput(
        digest="a" * 64,
        scope={"plan_id": uuid4(), "plan_hash": "e" * 64, "status": "reviewed", "authorization_revision": 1,
               "target_id": target, "target_version": 1, "attribution": "first_party", "outcome": "allowed"},
        source={"id": uuid4(), "target_id": target, "origin": "legacy", "confidence": "unverified", "finding_count": 3},
    ),)


def test_dispatch_passes_only_projected_inputs_and_does_not_use_os_tools(inputs, monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("Offline dispatch must not open a process or filesystem path")

    port = Mock()
    run, reservation = uuid4(), uuid4()
    tool = ToolId.SCOPE_RECORD_REVIEW
    port.start.return_value = StepWork(reservation, tool, inputs)
    handler = Mock(return_value=StepOutput(status="observed", citations=(inputs[0].digest,)))
    with monkeypatch.context() as guarded:
        guarded.setattr(subprocess, "Popen", deny)
        guarded.setattr(Path, "open", deny)
        dispatch_step(port, {tool: handler}, run, "white", "dispatch-test-key")
    handler.assert_called_once_with(StepWork(reservation, tool, inputs))
    port.finish.assert_called_once_with(run, "white", "dispatch-test-key", reservation,
                                        output=StepOutput(status="observed", citations=(inputs[0].digest,)),
                                        failure=None)


@pytest.mark.parametrize("proposed", [
    {"status": "observed", "citations": ("b" * 64,)},
    {"status": "inconclusive", "private_payload": "discard this"},
    StepOutput.model_construct(status="observed", citations=()),
])
def test_dispatch_discards_unattributed_or_untyped_output(inputs, proposed):
    port = Mock()
    run, reservation = uuid4(), uuid4()
    tool = ToolId.SCOPE_RECORD_REVIEW
    port.start.return_value = StepWork(reservation, tool, inputs)
    dispatch_step(port, {tool: lambda _: proposed}, run, "white", "dispatch-test-key")
    port.finish.assert_called_once_with(run, "white", "dispatch-test-key", reservation,
                                        output=None, failure="analysis_output_invalid")


def test_completed_or_processing_receipt_does_not_reinvoke_handler():
    port = Mock()
    tool = ToolId.SCOPE_RECORD_REVIEW
    port.start.return_value = {"state": "processing"}
    handler = Mock()
    assert dispatch_step(port, {tool: handler}, uuid4(), "white", "dispatch-test-key") == {"state": "processing"}
    handler.assert_not_called()
    port.finish.assert_not_called()


def test_event_review_distinguishes_matches_covered_negative_and_missing_source(inputs):
    scope = inputs[0].scope
    event = {"event_id": str(uuid4()), "occurred_at": "2026-01-01T14:10:00Z", "kind": "login-failure"}
    batch = {"target_id": str(scope.target_id), "producer": "identity-audit", "window_start": "2026-01-01T14:00:00Z",
             "window_end": "2026-01-01T15:00:00Z", "events": [event]}
    positive = OfflineInput(digest="b" * 64, scope=scope, source=batch)
    duplicate = OfflineInput(digest="c" * 64, scope=scope, source=batch)
    negative = OfflineInput(digest="d" * 64, scope=scope, source={**batch, "events": [{**event, "kind": "login-success"}]})
    other_producer = OfflineInput(digest="f" * 64, scope=scope, source={**batch, "producer": "other-audit"})
    absent = event_review((*inputs, other_producer))
    assert (absent.status, absent.citations, absent.triage.batches_evaluated) == ("inconclusive", (), 0)
    covered = event_review((negative,))
    assert (covered.status, covered.citations, covered.triage.matching_events) == ("missing", (negative.digest,), 0)
    matched = event_review((duplicate, negative, positive, other_producer))
    assert matched.status == "observed" and matched.citations == (positive.digest, duplicate.digest, negative.digest)
    assert (matched.triage.batches_evaluated, matched.triage.matching_events) == (3, 1)
    with pytest.raises(ValueError, match="Unknown event rule"):
        event_review((positive,), "unsafe-expression")
    with pytest.raises(ValueError):
        AnalysisDraft(permission_id=uuid4(), permission_revision=1, selection_version=1,
                      sources=(positive.digest,), event_rule="unsafe-expression")


def test_coverage_matrix_excludes_gaps_and_unrelated_batches_from_the_denominator(inputs):
    scope = inputs[0].scope

    def batch(digest, start, end, events=(), producer="identity-audit"):
        return OfflineInput(digest=digest * 64, scope=scope, source={
            "target_id": str(scope.target_id), "producer": producer,
            "window_start": f"2026-01-01T14:{start}:00Z", "window_end": f"2026-01-01T14:{end}:00Z", "events": events,
        })

    observations = (
        batch("b", "05", "10", [{"event_id": str(uuid4()), "occurred_at": "2026-01-01T14:05:00Z", "kind": "login-failure"}]),
        batch("c", "20", "25"), batch("d", "25", "30"), batch("e", "42", "46"),
        batch("f", "40", "50", producer="other-audit"),
    )
    scenario = CoverageScenario(scenario_id=uuid4(), target_id=scope.target_id, checks=[
        {"control_id": name, "rule_id": "identity-login-failure-v1",
         "window_start": f"2026-01-01T11:{start}:00-03:00", "window_end": f"2026-01-01T14:{end}:00Z"}
        for name, start, end in (("expected-detection", "00", "10"), ("complete-negative", "20", "30"), ("gap", "40", "50"))
    ])
    result = coverage_review(observations, scenario)
    assert result == coverage_review(tuple(reversed(observations)), scenario)
    assert (result.coverage.detected, result.coverage.evaluated) == (1, 2)
    assert [(row.status, row.citations) for row in result.coverage.rows] == [
        ("detected", ("b" * 64,)), ("not_detected", ("c" * 64, "d" * 64)), ("no_data", ("e" * 64,)),
    ]
    assert coverage_review((observations[-1],), scenario).coverage.evaluated == 0
    complete_negative = coverage_review(observations[1:3], scenario)
    assert (complete_negative.status, complete_negative.coverage.evaluated) == ("missing", 1)
    assert coverage_review(observations, scenario.model_copy(update={"target_id": uuid4()})).coverage.evaluated == 0
    with pytest.raises(ValueError, match="Expected distinct rule and window combinations"):
        CoverageScenario(scenario_id=uuid4(), target_id=scope.target_id,
                         checks=(scenario.checks[0], scenario.checks[0].model_copy(update={"control_id": "duplicate"})))
