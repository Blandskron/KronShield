"""Deterministic selection and invocation of registered offline capabilities."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from application.access import AccessError
from application.evidence import ControlObservations, Digest, EvidenceModel, Revision
from domain.team_modes import CapabilityStep, TeamMode, TeamStep, ToolId


class ScopeReference(EvidenceModel):
    plan_id: UUID
    plan_hash: Digest
    status: Literal["reviewed"]
    authorization_revision: Revision
    target_id: UUID
    target_version: int
    attribution: Literal["first_party"]
    outcome: Literal["allowed"]


class LegacySummary(EvidenceModel):
    id: UUID
    target_id: UUID
    origin: Literal["legacy"]
    confidence: Literal["unverified"]
    finding_count: Annotated[int, Field(ge=0)]


class OfflineInput(EvidenceModel):
    digest: Digest
    scope: ScopeReference
    source: LegacySummary | ControlObservations


class StepOutput(EvidenceModel):
    status: Literal["observed", "inconclusive"]
    citations: Annotated[tuple[Digest, ...], Field(max_length=50)] = ()

    @model_validator(mode="after")
    def check_citations(self):
        if len(set(self.citations)) != len(self.citations) or (self.status == "observed" and not self.citations):
            raise ValueError("Expected unique citations for an observation")
        return self


@dataclass(frozen=True)
class StepWork:
    reservation_id: UUID
    tool: ToolId
    inputs: tuple[OfflineInput, ...]


class DispatchPort(Protocol):
    def start(self, analysis_id: UUID, step_id: str, key: str, available: frozenset[ToolId]) -> StepWork | dict: ...

    def finish(self, analysis_id: UUID, step_id: str, key: str, reservation_id: UUID, *,
               output: StepOutput | None, failure: str | None) -> dict: ...


OfflineHandler = Callable[[tuple[OfflineInput, ...]], StepOutput]


def next_tool(snapshot: dict, completed: set[str], requested: str) -> ToolId:
    mode = TeamMode.model_validate(snapshot["manifest"])
    if mode.digest != snapshot["manifest_digest"]:
        raise AccessError(409, "analysis_manifest_changed")
    steps = {step.id: step for step in mode.workflow}
    if requested not in steps:
        raise AccessError(422, "unknown_analysis_step")
    next_step = next((name for name in mode.execution_order() if name not in completed), None)
    if next_step != requested:
        raise AccessError(409, "analysis_transition_invalid")
    step = steps[requested]
    if isinstance(step, CapabilityStep):
        return step.tool
    if isinstance(step, TeamStep):
        stage_data = snapshot["stage_manifests"].get(step.id)
        if stage_data is not None:
            stage = TeamMode.model_validate(stage_data)
            if ((stage.id, stage.version) == (step.team, step.version)
                    and len(stage.workflow) == 1 and isinstance(stage.workflow[0], CapabilityStep)):
                return stage.workflow[0].tool
    raise AccessError(409, "analysis_manifest_changed")


def validate_output(value: object, inputs: tuple[OfflineInput, ...]) -> StepOutput:
    result = StepOutput.model_validate(value.model_dump() if isinstance(value, StepOutput) else value)
    if set(result.citations) - {item.digest for item in inputs}:
        raise ValueError("Citations must come from authorized inputs")
    return result


def dispatch_step(port: DispatchPort, registry: Mapping[ToolId, OfflineHandler],
                  analysis_id: UUID, step_id: str, key: str) -> dict:
    """Use only in-process handlers installed by trusted application wiring."""
    started = port.start(analysis_id, step_id, key, frozenset(registry))
    if isinstance(started, dict):
        return started
    try:
        proposed = registry[started.tool](started.inputs)
        # Validate again so a handler cannot use model_construct/model_copy to bypass the output shape.
        result = validate_output(proposed, started.inputs)
    except (ValidationError, ValueError):
        return port.finish(analysis_id, step_id, key, started.reservation_id,
                           output=None, failure="analysis_output_invalid")
    except Exception:
        return port.finish(analysis_id, step_id, key, started.reservation_id,
                           output=None, failure="analysis_handler_failed")
    return port.finish(analysis_id, step_id, key, started.reservation_id, output=result, failure=None)
