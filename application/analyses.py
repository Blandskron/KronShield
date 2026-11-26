"""Inputs and budget arithmetic for offline analysis records."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from application.access import AccessError
from application.evidence import Digest, EvidenceModel, Revision
from domain.team_modes import TeamMode

PROJECT_CONCURRENCY = 2
EventRuleId = Literal["identity-login-failure-v1"]
DEFAULT_EVENT_RULE: EventRuleId = "identity-login-failure-v1"


class AnalysisDraft(EvidenceModel):
    permission_id: UUID
    permission_revision: Revision
    selection_version: Annotated[int, Field(strict=True, gt=0, le=9007199254740991)]
    sources: Annotated[tuple[Digest, ...], Field(min_length=1, max_length=50)]
    event_rule: EventRuleId | None = None

    @model_validator(mode="after")
    def unique_sources(self):
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Expected unique source digests")
        return self


Quantity = Annotated[int, Field(strict=True, ge=0, le=4194304)]


class Usage(EvidenceModel):
    input_bytes: Quantity = 0
    calls: Quantity = 0
    input_tokens: Quantity = 0
    output_tokens: Quantity = 0

    @model_validator(mode="after")
    def tokens_require_call(self):
        if not self.calls and (self.input_tokens or self.output_tokens):
            raise ValueError("Token usage requires an inference call")
        return self

    def fits(self, ceiling: "Usage") -> bool:
        return (
            self.input_bytes <= ceiling.input_bytes and self.calls <= ceiling.calls
            and self.input_tokens <= ceiling.input_tokens and self.output_tokens <= ceiling.output_tokens
        )


def pilot_budget(mode: TeamMode) -> dict:
    return {
        "steps": mode.limits.max_steps,
        "seconds": mode.limits.max_seconds,
        "usage": Usage(input_bytes=mode.limits.max_input_bytes, calls=min(6, mode.limits.max_steps),
                       input_tokens=12000, output_tokens=3000).model_dump(),
    }


def check_budget(budget: dict, total: dict, request: Usage) -> None:
    if total["steps"] >= budget["steps"] or any(
        total[field] + value > budget["usage"][field] for field, value in request.model_dump().items()
    ):
        raise AccessError(409, "analysis_budget_exceeded")
