from uuid import uuid4

import pytest
from pydantic import ValidationError

from application.access import AccessError
from application.analyses import AnalysisDraft, Usage, check_budget, pilot_budget
from domain.team_modes import TEAM_CATALOG, TeamId


def test_immutable_analysis_request_requires_unique_source_digests():
    fields = {"permission_id": uuid4(), "permission_revision": 1, "selection_version": 3}
    with pytest.raises(ValidationError, match="unique source"):
        AnalysisDraft(**fields, sources=["a" * 64, "a" * 64])
    with pytest.raises(ValidationError):
        AnalysisDraft(**fields, sources=["bad digest"])


@pytest.mark.parametrize("mode", [TeamId.RED, TeamId.RAINBOW])
def test_pilot_budget_defaults_follow_frozen_mode_limits(mode):
    limits = pilot_budget(TEAM_CATALOG[mode])
    expected_steps, expected_seconds, expected_bytes = (1, 30, 1048576) if mode is TeamId.RED else (9, 120, 4194304)
    assert limits == {
        "steps": expected_steps,
        "seconds": expected_seconds,
        "usage": {"input_bytes": expected_bytes, "calls": min(expected_steps, 6),
                  "input_tokens": 12000, "output_tokens": 3000},
    }


@pytest.mark.parametrize("field", ["steps", "input_bytes", "calls", "input_tokens", "output_tokens"])
def test_accumulated_budget_rejects_each_exhausted_resource(field):
    limits = pilot_budget(TEAM_CATALOG[TeamId.RAINBOW])
    total = {"steps": 0, **Usage().model_dump()}
    total[field] = limits["steps"] if field == "steps" else limits["usage"][field]
    with pytest.raises(AccessError, match="analysis_budget_exceeded"):
        check_budget(limits, total, Usage(input_bytes=1, calls=1, input_tokens=1, output_tokens=1))


def test_usage_requires_nonnegative_counts_and_an_inference_call_for_tokens():
    with pytest.raises(ValidationError):
        Usage(input_bytes=-1)
    with pytest.raises(ValidationError):
        Usage(input_tokens=1)
    assert Usage(input_bytes=40).fits(Usage(input_bytes=50))
    assert not Usage(output_tokens=51, calls=1).fits(Usage(output_tokens=50, calls=1))
