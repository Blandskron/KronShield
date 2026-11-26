"""Read a bounded SARIF 2.1.0 profile without resolving its identifiers."""

import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Producer = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$")]
Version = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")]
Repository = Annotated[str, Field(
    max_length=300, pattern=r"^https://[a-z0-9][a-z0-9.-]*(/[A-Za-z0-9_.-]+)+$",
)]
Commit = Annotated[str, Field(pattern=r"^([0-9a-f]{40}|[0-9a-f]{64})$")]
RuleId = Annotated[str, Field(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*(/[A-Za-z0-9_.:-]+)*$")]
Line = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
RelativePath = Annotated[str, Field(max_length=240, pattern=r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")]


class SarifModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class SarifProvenance(SarifModel):
    producer: Producer
    producer_version: Version
    repository_uri: Repository
    revision_id: Commit

    @field_validator("repository_uri")
    @classmethod
    def check_repository_path(cls, value: str) -> str:
        if any(segment in {".", ".."} for segment in value.split("/")[3:]):
            raise ValueError("Repository identifiers require canonical path segments")
        return value


class Driver(SarifModel):
    name: Producer
    version: Version


class Tool(SarifModel):
    driver: Driver


class RepositoryRevision(SarifModel):
    repositoryUri: Repository
    revisionId: Commit


class ArtifactLocation(SarifModel):
    uri: RelativePath

    @field_validator("uri")
    @classmethod
    def require_relative_segments(cls, value: str) -> str:
        if any(segment.endswith(".") for segment in value.split("/")):
            raise ValueError("Expected a relative path with canonical segments")
        return value


class Region(SarifModel):
    startLine: Line
    endLine: Line | None = None

    @model_validator(mode="after")
    def check_range(self):
        if self.endLine is not None and self.endLine < self.startLine:
            raise ValueError("End line precedes start line")
        return self


class PhysicalLocation(SarifModel):
    artifactLocation: ArtifactLocation
    region: Region | None = None


class Location(SarifModel):
    physicalLocation: PhysicalLocation


class Message(SarifModel):
    text: Annotated[str, Field(min_length=1, max_length=2048)]


class Result(SarifModel):
    ruleId: RuleId
    message: Message
    locations: Annotated[tuple[Location, ...], Field(min_length=1, max_length=1)]
    level: Literal["none", "note", "warning", "error"] | None = None


class Run(SarifModel):
    tool: Tool
    versionControlProvenance: Annotated[tuple[RepositoryRevision, ...], Field(min_length=1, max_length=1)]
    results: Annotated[tuple[Result, ...], Field(max_length=500)]

    def provenance(self) -> SarifProvenance:
        repository = self.versionControlProvenance[0]
        return SarifProvenance(producer=self.tool.driver.name, producer_version=self.tool.driver.version,
                               repository_uri=repository.repositoryUri, revision_id=repository.revisionId)


class Report(SarifModel):
    version: Literal["2.1.0"]
    schema_uri: Literal[
        "https://json.schemastore.org/sarif-2.1.0.json",
        "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0-rtm.5.json",
    ] | None = Field(default=None, alias="$schema")
    runs: Annotated[tuple[Run, ...], Field(min_length=1, max_length=1)]


class SarifLocation(SarifModel):
    rule_id: RuleId
    path: RelativePath
    start_line: Line | None
    end_line: Line | None


class SarifProjection(SarifModel):
    target_id: UUID
    sarif_version: Literal["2.1.0"] = "2.1.0"
    provenance: SarifProvenance
    locations: Annotated[tuple[SarifLocation, ...], Field(max_length=500)]


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Expected unique JSON fields")
    return result


def read_report(payload: bytes) -> Run:
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (ValueError, RecursionError):
        raise ValueError("Expected unambiguous SARIF JSON in UTF-8") from None
    return Report.model_validate(data).runs[0]


def locations(run: Run) -> tuple[SarifLocation, ...]:
    projected = []
    for item in run.results:
        location = item.locations[0].physicalLocation
        projected.append(SarifLocation(
            rule_id=item.ruleId, path=location.artifactLocation.uri,
            start_line=location.region.startLine if location.region else None,
            end_line=location.region.endLine if location.region else None,
        ))
    return tuple(projected)
