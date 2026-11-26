import subprocess
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from application.access import AccessError
from application.analysis_dispatch import OfflineInput, StepOutput, StepWork, dispatch_step, next_tool
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
    handler.assert_called_once_with(inputs)
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
