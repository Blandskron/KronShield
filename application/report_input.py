"""Bounded input for local reports and optional summaries."""

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from domain.models import FindingConfidence, FindingStatus


_MAX_JSON_BYTES = 1024 * 1024
_TEXT = Annotated[str, StringConstraints(max_length=16384)]
_LOCATION = Annotated[str, StringConstraints(max_length=8192)]
_HEADER = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class _ReportInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True, hide_input_in_errors=True)


class FindingExtras(_ReportInput):
    missing_security_headers: tuple[_HEADER, ...] = Field(default=(), max_length=64)
    signatures: tuple[_HEADER, ...] = Field(default=(), max_length=64)


class ReportFinding(_ReportInput):
    type: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    detail: _TEXT
    url: _LOCATION | None = None
    payload: _TEXT | None = None
    extra: FindingExtras | None = None
    status: FindingStatus | None = None
    confidence: FindingConfidence | None = None


class SavedAudit(_ReportInput):
    url: Annotated[str, StringConstraints(min_length=1, max_length=8192)]
    findings: tuple[ReportFinding, ...] = Field(max_length=1000)

    def summary_input(self) -> dict:
        """Keep the opt-in provider payload separate from local evidence."""
        return {"findings": [{"type": item.type, "detail": item.detail} for item in self.findings]}


def read_saved_audit(path: Path) -> SavedAudit:
    if not path.is_file():
        raise ValueError("Expected a regular report input file")
    with path.open("rb") as source:
        raw = source.read(_MAX_JSON_BYTES + 1)
    if len(raw) > _MAX_JSON_BYTES:
        raise ValueError("Report input exceeds 1 MiB")
    return SavedAudit.model_validate_json(raw)
