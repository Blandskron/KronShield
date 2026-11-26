"""Deterministic selection and invocation of registered offline capabilities."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator

from application.access import AccessError
from application.analyses import DEFAULT_EVENT_RULE, EventRuleId
from application.evidence import ControlObservations, Digest, EventBatch, EvidenceModel, Revision, projection_bytes
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
    source: LegacySummary | ControlObservations | EventBatch

    @field_validator("source", mode="before")
    @classmethod
    def parse_event_projection(cls, value):
        if isinstance(value, dict) and "events" in value:
            return EventBatch.model_validate_json(projection_bytes(value))
        return value


class EventTriage(EvidenceModel):
    rule_id: EventRuleId
    batches_evaluated: Annotated[int, Field(strict=True, ge=0, le=50)]
    matching_events: Annotated[int, Field(strict=True, ge=0, le=100000)]


class StepOutput(EvidenceModel):
    status: Literal["observed", "missing", "inconclusive"]
    citations: Annotated[tuple[Digest, ...], Field(max_length=50)] = ()
    triage: EventTriage | None = None

    @model_validator(mode="after")
    def check_citations(self):
        if len(set(self.citations)) != len(self.citations) or (self.status != "inconclusive" and not self.citations):
            raise ValueError("Expected unique citations for an observation")
        return self


def event_review(inputs: tuple[OfflineInput, ...], rule_id: EventRuleId = DEFAULT_EVENT_RULE) -> StepOutput:
    """Evaluate the reviewed v1 identity rule using only declared event fields."""
    if rule_id != DEFAULT_EVENT_RULE:
        raise ValueError("Unknown event rule")
    batches = [(item.digest, item.source) for item in inputs
               if isinstance(item.source, EventBatch) and item.source.producer == "identity-audit"
               and item.source.target_id == item.scope.target_id]
    matches = {(batch.target_id, event.event_id) for _, batch in batches
               for event in batch.events if event.kind == "login-failure"}
    status = "observed" if matches else "missing" if batches else "inconclusive"
    return StepOutput(status=status, citations=tuple(sorted(digest for digest, _ in batches)),
                      triage=EventTriage(rule_id=rule_id, batches_evaluated=len(batches), matching_events=len(matches)))


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
