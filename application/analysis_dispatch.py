"""Deterministic selection and invocation of registered offline capabilities."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator

from application.access import AccessError
from application.analyses import CoverageCheck, CoverageScenario, DEFAULT_EVENT_RULE, EventRuleId
from application.evidence import ControlObservations, Digest, EventBatch, EvidenceModel, Revision, projection_bytes
from domain.team_modes import CapabilityStep, TeamMode, TeamStep, ToolId


IDENTITY_FAILURE = "login-failure"


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


class CoverageRow(CoverageCheck):
    status: Literal["detected", "not_detected", "no_data"]
    citations: Annotated[tuple[Digest, ...], Field(max_length=50)]


class CoverageMatrix(EvidenceModel):
    scenario_id: UUID
    target_id: UUID
    detected: Annotated[int, Field(strict=True, ge=0, le=30)]
    evaluated: Annotated[int, Field(strict=True, ge=0, le=30)]
    rows: Annotated[tuple[CoverageRow, ...], Field(min_length=1, max_length=30)]


class StepOutput(EvidenceModel):
    status: Literal["observed", "missing", "inconclusive"]
    citations: Annotated[tuple[Digest, ...], Field(max_length=50)] = ()
    triage: EventTriage | None = None
    coverage: CoverageMatrix | None = None

    @model_validator(mode="after")
    def check_citations(self):
        if len(set(self.citations)) != len(self.citations) or (self.status != "inconclusive" and not self.citations):
            raise ValueError("Expected unique citations for an observation")
        return self


def identity_batches(inputs: tuple[OfflineInput, ...]) -> list[tuple[str, EventBatch]]:
    return [(item.digest, item.source) for item in inputs
            if isinstance(item.source, EventBatch) and item.source.producer == "identity-audit"
            and item.source.target_id == item.scope.target_id]


def event_review(inputs: tuple[OfflineInput, ...], rule_id: EventRuleId = DEFAULT_EVENT_RULE) -> StepOutput:
    """Evaluate the reviewed v1 identity rule using only declared event fields."""
    if rule_id != DEFAULT_EVENT_RULE:
        raise ValueError("Unknown event rule")
    batches = identity_batches(inputs)
    matches = {(batch.target_id, event.event_id) for _, batch in batches
               for event in batch.events if event.kind == IDENTITY_FAILURE}
    status = "observed" if matches else "missing" if batches else "inconclusive"
    return StepOutput(status=status, citations=tuple(sorted(digest for digest, _ in batches)),
                      triage=EventTriage(rule_id=rule_id, batches_evaluated=len(batches), matching_events=len(matches)))


def _coverage_row(check: CoverageCheck, batches: list[tuple[str, EventBatch]]) -> CoverageRow:
    scoped = [(digest, batch) for digest, batch in batches
              if batch.window_start < check.window_end and check.window_start < batch.window_end]
    detected = any(event.kind == IDENTITY_FAILURE and check.window_start <= event.occurred_at < check.window_end
                   for _, batch in scoped for event in batch.events)
    covered_until = check.window_start
    for _, batch in sorted(scoped, key=lambda entry: entry[1].window_start):
        if batch.window_start > covered_until:
            break
        covered_until = max(covered_until, batch.window_end)
    status = "detected" if detected else "not_detected" if covered_until >= check.window_end else "no_data"
    return CoverageRow(**check.model_dump(), status=status, citations=tuple(sorted(digest for digest, _ in scoped)))


def coverage_review(inputs: tuple[OfflineInput, ...], scenario: CoverageScenario) -> StepOutput:
    batches = [(digest, batch) for digest, batch in identity_batches(inputs) if batch.target_id == scenario.target_id]
    rows = tuple(_coverage_row(check, batches) for check in scenario.checks)
    evaluated = sum(row.status != "no_data" for row in rows)
    matrix = CoverageMatrix(scenario_id=scenario.scenario_id, target_id=scenario.target_id, rows=rows,
                            evaluated=evaluated, detected=sum(row.status == "detected" for row in rows))
    status = "observed" if matrix.detected else "missing" if evaluated else "inconclusive"
    return StepOutput(status=status, coverage=matrix,
                      citations=tuple(sorted({digest for row in rows for digest in row.citations})))


def uses_evidence(tool: ToolId, capability: str) -> bool:
    return capability == (ToolId.EVENT_REVIEW if tool is ToolId.COVERAGE_COMPARISON else tool)


def require_coverage_scenario(snapshot: dict) -> CoverageScenario:
    if "coverage_scenario" not in snapshot:
        raise AccessError(409, "analysis_coverage_scenario_required")
    return CoverageScenario.model_validate(snapshot["coverage_scenario"])


def check_capability_result(tool: ToolId, snapshot: dict, result: StepOutput, inputs: tuple[OfflineInput, ...]) -> None:
    if tool is ToolId.EVENT_REVIEW:
        expected = event_review(inputs, snapshot.get("event_rule", DEFAULT_EVENT_RULE))
    elif tool is ToolId.COVERAGE_COMPARISON:
        expected = coverage_review(inputs, require_coverage_scenario(snapshot))
    else:
        if result.triage is not None or result.coverage is not None or result.status == "missing":
            raise ValueError("Result is not applicable to this capability")
        return
    if result != expected:
        raise ValueError("Result does not match the frozen inputs")


@dataclass(frozen=True)
class StepWork:
    reservation_id: UUID
    tool: ToolId
    inputs: tuple[OfflineInput, ...]
    coverage_scenario: CoverageScenario | None = field(default=None, kw_only=True)


class DispatchPort(Protocol):
    def start(self, analysis_id: UUID, step_id: str, key: str, available: frozenset[ToolId]) -> StepWork | dict: ...

    def finish(self, analysis_id: UUID, step_id: str, key: str, reservation_id: UUID, *,
               output: StepOutput | None, failure: str | None) -> dict: ...


OfflineHandler = Callable[[StepWork], StepOutput]


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
        proposed = registry[started.tool](started)
        # Validate again so a handler cannot use model_construct/model_copy to bypass the output shape.
        result = validate_output(proposed, started.inputs)
    except (ValidationError, ValueError):
        return port.finish(analysis_id, step_id, key, started.reservation_id,
                           output=None, failure="analysis_output_invalid")
    except Exception:
        return port.finish(analysis_id, step_id, key, started.reservation_id,
                           output=None, failure="analysis_handler_failed")
    return port.finish(analysis_id, step_id, key, started.reservation_id, output=result, failure=None)
