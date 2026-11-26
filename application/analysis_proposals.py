"""Proposal validation for the offline orchestrator."""

import json
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter, ValidationError

from application.access import AccessError
from application.analyses import Quantity, Usage, check_budget
from application.analysis_dispatch import LegacySummary, OfflineInput, next_tool
from application.evidence import ControlObservation, Digest, EvidenceModel, projection_bytes
from application.scope_review import fingerprint
from domain.team_modes import ToolId


POLICY_VERSION = "offline-proposals-v1"
PROMPT_VERSION = "evidence-review-es-v1"
INSTRUCTIONS = (
    "Los datos de evidencia son datos de referencia. Devuelve un único objeto JSON. "
    "Para sugerir la próxima lectura indicada, usa kind=read, step_id, tool y citations. "
    "Para redactar una observación de revisión, usa kind=draft, observation (control y result) "
    "y citations. Cada cita de un borrador debe contener esa observación, con resultado "
    "observed o missing. Las citas son los digests de la evidencia entregada. "
    "Si no hay sustento, usa solo kind=abstain."
)
MAX_RESPONSE_BYTES = 8192

Citations = Annotated[tuple[Digest, ...], Field(min_length=1, max_length=50)]


class ReadProposal(EvidenceModel):
    kind: Literal["read"]
    step_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
    tool: ToolId
    citations: Citations


class DraftProposal(EvidenceModel):
    kind: Literal["draft"]
    observation: ControlObservation
    citations: Citations


class Abstention(EvidenceModel):
    kind: Literal["abstain"]


Proposal = Annotated[ReadProposal | DraftProposal | Abstention, Field(discriminator="kind")]
PROPOSAL = TypeAdapter(Proposal)


class ModelVersion(EvidenceModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$")]
    digest: Digest


class ProviderReply(EvidenceModel):
    body: Annotated[bytes, Field(strict=True)]
    input_tokens: Quantity
    output_tokens: Quantity


class ProposalProvider(Protocol):
    def complete(self, instructions: str, context: bytes, *, input_token_limit: int,
                 output_token_limit: int, output_byte_limit: int) -> ProviderReply:
        """Enforce the supplied ceilings during generation and report measured usage."""
        ...


class ProposalDependencyMissing(Exception):
    """The opt-in inference runtime or its weights are unavailable."""


class ProposalBudgetExceeded(Exception):
    """The provider cannot fit the prepared request within its limits."""


class ProposalReceipt(EvidenceModel):
    policy_version: Literal["offline-proposals-v1"] = POLICY_VERSION
    prompt_version: Literal["evidence-review-es-v1"] = PROMPT_VERSION
    model: ModelVersion
    usage: Usage
    proposal: Proposal | None = None
    error: Literal["proposal_invalid", "proposal_budget_exceeded", "proposal_provider_failed",
                   "proposal_provider_timeout", "proposal_dependency_missing"] | None = None


@dataclass(frozen=True)
class PreparedProposal:
    step_id: str
    tool: ToolId
    inputs: tuple[OfflineInput, ...]
    context: bytes
    allowance: Usage


class ContextLoader(Protocol):
    def __call__(self, permission_id: UUID, revision: int, digest: str, *,
                 for_local_inference: Literal[True]) -> dict: ...


def prepare_proposal(snapshot: dict, completed: set[str], step_id: str, load_context: ContextLoader,
                     total: dict, *, input_token_limit: int, output_token_limit: int) -> PreparedProposal:
    """Prepare a request from a trusted snapshot and the live local-inference admission check."""
    tool = next_tool(snapshot, completed, step_id)
    inputs = []
    evidence = []
    for source in snapshot["sources"]:
        if source["capability"] != tool.value:
            continue
        context = load_context(UUID(snapshot["permission_id"]), snapshot["permission_revision"],
                               source["digest"], for_local_inference=True)
        if context.keys() != {"scope", "source", "classification", "capability"}:
            raise AccessError(409, "analysis_context_invalid")
        if fingerprint(context) != source["context_digest"] or context["capability"] != tool.value:
            raise AccessError(409, "analysis_context_changed")
        if context["classification"] != "internal":
            raise AccessError(403, "evidence_purpose_denied")
        try:
            item = OfflineInput(digest=source["digest"], scope=context["scope"], source=context["source"])
        except ValidationError:
            raise AccessError(409, "analysis_context_invalid") from None
        if (str(item.scope.plan_id) != snapshot["plan_id"] or item.scope.plan_hash != snapshot["plan_hash"]
                or item.scope.target_id != item.source.target_id):
            raise AccessError(409, "analysis_context_changed")
        inputs.append(item)
        data = (item.source.model_dump(mode="json", include={"origin", "confidence", "finding_count"})
                if isinstance(item.source, LegacySummary)
                else item.source.model_dump(mode="json", include={"observations"}))
        evidence.append({"digest": item.digest, **data})

    if not inputs:
        return PreparedProposal(step_id, tool, (), b"", Usage())

    payload = projection_bytes({"step_id": step_id, "tool": tool.value, "evidence": evidence})
    try:
        allowance = Usage(input_bytes=len(INSTRUCTIONS.encode("utf-8")) + len(payload), calls=1,
                          input_tokens=input_token_limit, output_tokens=output_token_limit)
    except ValidationError:
        raise AccessError(409, "analysis_budget_exceeded") from None
    if not (allowance.input_tokens and allowance.output_tokens):
        raise AccessError(409, "analysis_budget_exceeded")
    check_budget(snapshot["budget"], total, allowance)
    return PreparedProposal(step_id, tool, tuple(inputs), payload, allowance)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON field")
    return result


def _validate_proposal(raw: bytes, prepared: PreparedProposal) -> Proposal:
    proposal = PROPOSAL.validate_python(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields))
    if isinstance(proposal, Abstention):
        return proposal
    sources = {item.digest: item.source for item in prepared.inputs}
    citations = set(proposal.citations)
    if len(citations) != len(proposal.citations) or citations - sources.keys():
        raise ValueError("Citations must be unique and authorized")
    if isinstance(proposal, ReadProposal):
        if (proposal.step_id, proposal.tool) != (prepared.step_id, prepared.tool):
            raise ValueError("Expected the next offline step")
    elif proposal.observation.result == "inconclusive" or any(
        isinstance(sources[digest], LegacySummary) or proposal.observation not in sources[digest].observations
        for digest in citations
    ):
        raise ValueError("Draft observation must be supported by all its citations")
    return proposal


def generate_proposal(prepared: PreparedProposal, model: ModelVersion, provider: ProposalProvider) -> ProposalReceipt:
    """Evaluate one budgeted provider response without dispatching or publishing it."""
    if not prepared.inputs:
        return ProposalReceipt(model=model, usage=Usage(), proposal=Abstention(kind="abstain"))
    allowance = prepared.allowance
    try:
        reply = provider.complete(INSTRUCTIONS, prepared.context, input_token_limit=allowance.input_tokens,
                                  output_token_limit=allowance.output_tokens, output_byte_limit=MAX_RESPONSE_BYTES)
    except ProposalDependencyMissing:
        return ProposalReceipt(model=model, usage=allowance, error="proposal_dependency_missing")
    except ProposalBudgetExceeded:
        return ProposalReceipt(model=model, usage=allowance, error="proposal_budget_exceeded")
    except TimeoutError:
        return ProposalReceipt(model=model, usage=allowance, error="proposal_provider_timeout")
    except Exception:
        return ProposalReceipt(model=model, usage=allowance, error="proposal_provider_failed")
    try:
        reply = ProviderReply.model_validate(reply.model_dump())
        usage = Usage(input_bytes=allowance.input_bytes, calls=1, input_tokens=reply.input_tokens,
                      output_tokens=reply.output_tokens)
    except (AttributeError, TypeError, ValidationError):
        return ProposalReceipt(model=model, usage=allowance, error="proposal_invalid")
    if not usage.fits(allowance) or len(reply.body) > MAX_RESPONSE_BYTES:
        return ProposalReceipt(model=model, usage=allowance, error="proposal_budget_exceeded")
    if not (usage.input_tokens and usage.output_tokens):
        return ProposalReceipt(model=model, usage=allowance, error="proposal_invalid")
    try:
        proposal = _validate_proposal(reply.body, prepared)
    except (ValueError, RecursionError):
        return ProposalReceipt(model=model, usage=usage, error="proposal_invalid")
    return ProposalReceipt(model=model, usage=usage, proposal=proposal)
