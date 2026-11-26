"""Versioned metadata for project team modes and their offline workflows."""

import json
from collections.abc import Mapping
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TeamId(str, Enum):
    RED = "red"
    BLUE = "blue"
    PURPLE = "purple"
    YELLOW = "yellow"
    ORANGE = "orange"
    GREEN = "green"
    WHITE = "white"
    BLACK = "black"
    GOLD = "gold"
    RAINBOW = "rainbow"


class ToolId(str, Enum):
    CAPTURE_REVIEW = "capture-review"
    EVENT_REVIEW = "event-review"
    COVERAGE_COMPARISON = "coverage-comparison"
    CODE_REVIEW = "code-review"
    LEARNING_BRIEF = "learning-brief"
    REMEDIATION_COMPARISON = "remediation-comparison"
    SCOPE_RECORD_REVIEW = "scope-record-review"
    TABLETOP_SCENARIO = "tabletop-scenario"
    RISK_SUMMARY = "risk-summary"


class ArtifactKind(str, Enum):
    CAPTURE_PAIR = "capture-pair"
    EVENT_BATCH = "event-batch"
    SCENARIO = "scenario"
    SARIF = "sarif"
    REVIEWED_CASE = "reviewed-case"
    REMEDIATION_PAIR = "remediation-pair"
    SCOPE_PLAN = "scope-plan"
    REVIEWED_RESULTS = "reviewed-results"
    EVIDENCE_MANIFEST = "evidence-manifest"
    EXPOSURE_OBSERVATIONS = "exposure-observations"
    TRIAGE_OBSERVATIONS = "triage-observations"
    COVERAGE_MATRIX = "coverage-matrix"
    CODE_REVIEW_DRAFT = "code-review-draft"
    LEARNING_CARD = "learning-card"
    REMEDIATION_RECORD = "remediation-record"
    SCOPE_MINUTES = "scope-minutes"
    CONTINUITY_RECORD = "continuity-record"
    RISK_BRIEF = "risk-brief"
    RAINBOW_MATRIX = "rainbow-matrix"


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisLimits(CatalogModel):
    """Planning ceilings for the offline analysis, independent of network budgets."""

    max_steps: int = Field(gt=0, strict=True)
    max_input_bytes: int = Field(gt=0, strict=True)
    max_seconds: int = Field(gt=0, strict=True)


class WorkflowStep(CatalogModel):
    id: str = Field(min_length=1)
    after: tuple[str, ...] = ()


class CapabilityStep(WorkflowStep):
    kind: Literal["capability"] = "capability"
    tool: ToolId


class TeamStep(WorkflowStep):
    kind: Literal["team"] = "team"
    team: TeamId
    version: int = Field(gt=0, strict=True)


class TeamMode(CatalogModel):
    id: TeamId
    version: int = Field(gt=0, strict=True)
    label: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    input_kinds: tuple[ArtifactKind, ...] = Field(min_length=1)
    inputs: tuple[str, ...] = Field(min_length=1)
    output_kind: ArtifactKind
    output: str = Field(min_length=1)
    resources: tuple[str, ...] = ()
    limits: AnalysisLimits
    workflow: tuple[CapabilityStep | TeamStep, ...] = Field(min_length=1)
    status: Literal["pending"] = "pending"

    @property
    def eligible_for_analysis(self) -> bool:
        return self.id in {TeamId.WHITE, TeamId.BLUE}

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)

    @property
    def digest(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def execution_order(self) -> tuple[str, ...]:
        """Sort ready steps in declaration order and reject broken graphs."""
        remaining = {step.id: set(step.after) for step in self.workflow}
        if len(remaining) != len(self.workflow):
            raise ValueError(f"Duplicate step in {self.id.value}")
        for step_id, prerequisites in remaining.items():
            if prerequisites - remaining.keys():
                raise ValueError(f"Unknown dependency in {self.id.value}/{step_id}")
        order = []
        while remaining:
            ready = [step_id for step_id, prerequisites in remaining.items() if not prerequisites]
            if not ready:
                raise ValueError(f"Dependency cycle in {self.id.value}")
            order.extend(ready)
            for step_id in ready:
                del remaining[step_id]
            for prerequisites in remaining.values():
                prerequisites.difference_update(ready)
        return tuple(order)


def build_catalog(modes: tuple[TeamMode, ...]) -> Mapping[TeamId, TeamMode]:
    catalog = {mode.id: mode for mode in modes}
    if len(catalog) != len(modes):
        raise ValueError("Duplicate team mode")
    if catalog.keys() != set(TeamId):
        raise ValueError("Expected the nine specialties and Rainbow")
    specialties = set(TeamId) - {TeamId.RAINBOW}
    for mode in modes:
        mode.execution_order()
        if len(mode.workflow) > mode.limits.max_steps:
            raise ValueError(f"Workflow exceeds step limit in {mode.id.value}")
        if mode.id != TeamId.RAINBOW:
            if not all(isinstance(step, CapabilityStep) for step in mode.workflow):
                raise ValueError(f"Expected capability steps in {mode.id.value}")
            continue
        members = set()
        for step in mode.workflow:
            if not isinstance(step, TeamStep) or step.team not in specialties:
                raise ValueError("Rainbow requires specialty stages")
            if step.team in members or step.version != catalog[step.team].version:
                raise ValueError("Duplicate or unknown Rainbow specialty version")
            members.add(step.team)
        if members != specialties:
            raise ValueError("Rainbow requires all nine specialties")
    return MappingProxyType(catalog)


def _specialty(team: TeamId, tool: ToolId, purpose: str, input_kinds: tuple[ArtifactKind, ...],
               inputs: tuple[str, ...], output_kind: ArtifactKind, output: str,
               resources: tuple[str, ...] = ()) -> TeamMode:
    return TeamMode(id=team, version=1, label=f"{team.value.title()} Team", purpose=purpose,
                    input_kinds=input_kinds, inputs=inputs, output_kind=output_kind, output=output, resources=resources,
                    limits=AnalysisLimits(max_steps=1, max_input_bytes=1024 * 1024, max_seconds=30),
                    workflow=(CapabilityStep(id=tool.value, tool=tool),))


_SPECIALTIES = (
    _specialty(TeamId.RED, ToolId.CAPTURE_REVIEW, "Revisión de exposición con evidencia guardada",
               (ArtifactKind.CAPTURE_PAIR,),
               ("Captura autorizada y línea base comparable del mismo activo",),
               ArtifactKind.EXPOSURE_OBSERVATIONS, "Observaciones, sospechas e inconclusos con referencias"),
    _specialty(TeamId.BLUE, ToolId.EVENT_REVIEW, "Detección y triaje de eventos",
               (ArtifactKind.EVENT_BATCH,),
               ("Eventos JSON minimizados, fuente y ventana", "Regla local revisada"),
               ArtifactKind.TRIAGE_OBSERVATIONS, "Coincidencias, faltantes y limitaciones"),
    _specialty(TeamId.PURPLE, ToolId.COVERAGE_COMPARISON, "Evaluación de cobertura de detección",
               (ArtifactKind.SCENARIO, ArtifactKind.TRIAGE_OBSERVATIONS),
               ("Escenario sintético con resultado esperado", "Observaciones Blue del mismo escenario"),
               ArtifactKind.COVERAGE_MATRIX, "Matriz de detección y cobertura con estados de disponibilidad"),
    _specialty(TeamId.YELLOW, ToolId.CODE_REVIEW, "Revisión de código y requisitos de seguridad",
               (ArtifactKind.SARIF,),
               ("SARIF de un productor aprobado con revisión de repositorio",),
               ArtifactKind.CODE_REVIEW_DRAFT, "Borrador de revisión con referencia a regla, ubicación y requisito",
               ("SARIF 2.1.0", "OWASP ASVS 5.0.0", "NIST SSDF 1.1")),
    _specialty(TeamId.ORANGE, ToolId.LEARNING_BRIEF, "Aprendizaje de desarrollo seguro",
               (ArtifactKind.REVIEWED_CASE,),
               ("Caso revisado con permiso de reutilización o fixture sintético autorizado",
                "Destinatario y objetivo de aprendizaje"),
               ArtifactKind.LEARNING_CARD, "Ficha didáctica desidentificada y rúbrica"),
    _specialty(TeamId.GREEN, ToolId.REMEDIATION_COMPARISON, "Remediación verificable",
               (ArtifactKind.REVIEWED_CASE, ArtifactKind.REMEDIATION_PAIR),
               ("Observación revisada, responsable y criterio esperado",
                "Evidencia comparable anterior y posterior del mismo control"),
               ArtifactKind.REMEDIATION_RECORD, "Ficha de cambio con mejora observada, persistencia o resultado inconcluso"),
    _specialty(TeamId.WHITE, ToolId.SCOPE_RECORD_REVIEW, "Revisión de alcance y arbitraje",
               (ArtifactKind.SCOPE_PLAN,),
               ("Plan v1 con hash y metadatos autorizados de las decisiones",),
               ArtifactKind.SCOPE_MINUTES, "Acta de cobertura, exclusiones y responsables"),
    _specialty(TeamId.BLACK, ToolId.TABLETOP_SCENARIO, "Resiliencia mediante ejercicios de mesa",
               (ArtifactKind.SCENARIO,),
               ("Escenario sintético versionado y dependencias declaradas", "Decisiones humanas del ejercicio"),
               ArtifactKind.CONTINUITY_RECORD, "Ficha de continuidad con brechas y responsables", ("NIST SP 800-84",)),
    _specialty(TeamId.GOLD, ToolId.RISK_SUMMARY, "Gobierno de riesgo y priorización",
               (ArtifactKind.REVIEWED_RESULTS,),
               ("Resultados revisados, impacto, criticidad y fecha de corte",),
               ArtifactKind.RISK_BRIEF, "Resumen ejecutivo de prioridades, decisiones y propietarios", ("NIST CSF 2.0",)),
)

_RAINBOW = TeamMode(
    id=TeamId.RAINBOW, version=1, label="Rainbow Team", purpose="Evaluación integral del proyecto",
    input_kinds=(ArtifactKind.EVIDENCE_MANIFEST,),
    inputs=("Manifiesto de evidencia autorizado para las especialidades aplicables",),
    output_kind=ArtifactKind.RAINBOW_MATRIX,
    output="Matriz de nueve etapas con estados, evidencias y limitaciones",
    limits=AnalysisLimits(max_steps=9, max_input_bytes=4 * 1024 * 1024, max_seconds=120),
    workflow=(
        TeamStep(id="white", team=TeamId.WHITE, version=1),
        TeamStep(id="red", team=TeamId.RED, version=1, after=("white",)),
        TeamStep(id="blue", team=TeamId.BLUE, version=1, after=("white",)),
        TeamStep(id="yellow", team=TeamId.YELLOW, version=1, after=("white",)),
        TeamStep(id="black", team=TeamId.BLACK, version=1, after=("white",)),
        TeamStep(id="purple", team=TeamId.PURPLE, version=1, after=("blue",)),
        TeamStep(id="orange", team=TeamId.ORANGE, version=1, after=("red", "yellow")),
        TeamStep(id="green", team=TeamId.GREEN, version=1, after=("red", "yellow")),
        TeamStep(id="gold", team=TeamId.GOLD, version=1,
                 after=("white", "red", "blue", "yellow", "black", "purple", "orange", "green")),
    ),
)

TEAM_CATALOG = build_catalog((*_SPECIALTIES, _RAINBOW))
