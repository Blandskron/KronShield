"""Exercise the opt-in provider with synthetic evidence inside its private network."""

import argparse
from time import perf_counter

from application.analyses import Usage, pilot_budget
from application.analysis_proposals import DraftProposal, generate_proposal, prepare_proposal
from application.scope_review import fingerprint
from domain.team_modes import TEAM_CATALOG, TeamId
from infra.local_inference import MODEL, LocalProposalProvider


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--missing", action="store_true")
    args = parser.parse_args()
    team = TEAM_CATALOG[TeamId.WHITE]
    plan_id = "00000000-0000-0000-0000-000000000001"
    target_id = "00000000-0000-0000-0000-000000000002"
    observation = {"control": "logging", "result": "missing"}
    context = {
        "scope": {"plan_id": plan_id, "plan_hash": "e" * 64, "status": "reviewed", "authorization_revision": 1,
                  "target_id": target_id, "target_version": 1, "attribution": "first_party", "outcome": "allowed"},
        "source": {"target_id": target_id, "observations": [observation]},
        "classification": "internal", "capability": "scope-record-review",
    }
    digest = fingerprint(context)
    snapshot = {
        "manifest": team.model_dump(mode="json"), "manifest_digest": team.digest, "stage_manifests": {},
        "plan_id": plan_id, "plan_hash": context["scope"]["plan_hash"], "permission_id": plan_id,
        "permission_revision": 1, "budget": pilot_budget(team),
        "sources": [{"digest": digest, "context_digest": digest, "capability": context["capability"]}],
    }

    def load_fixture(_permission_id, _revision, _digest, *, for_local_inference):
        if not for_local_inference:
            raise ValueError("Expected local inference admission")
        return context

    prepared = prepare_proposal(snapshot, set(), team.execution_order()[0], load_fixture,
                                {"steps": 0, **Usage().model_dump()}, input_token_limit=512, output_token_limit=150)
    started = perf_counter()
    receipt = generate_proposal(prepared, MODEL, LocalProposalProvider())
    print(f"{perf_counter() - started:.2f}s {receipt.model_dump_json()}")
    if args.missing:
        return int(receipt.error != "proposal_dependency_missing")
    return int(not isinstance(receipt.proposal, DraftProposal))


if __name__ == "__main__":
    raise SystemExit(main())
