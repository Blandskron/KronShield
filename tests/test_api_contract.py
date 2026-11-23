import json
from pathlib import Path


from contracts.export import specification


def test_versioned_contract_matches_and_describes_cursor_and_problem():
    contract_path = Path(__file__).resolve().parents[1] / "contracts" / "openapi-v1.json"
    schema = json.loads(contract_path.read_text(encoding="utf-8"))
    # The publishing workflow checks the complete serialized contract on the pinned generator.
    current = specification()
    assert schema["info"] == current["info"]
    assert set(schema["paths"]) == set(current["paths"])
    page = schema["paths"]["/api/v1/projects/{project_id}/targets"]["get"]
    assert {"after", "limit"} <= {parameter["name"] for parameter in page["parameters"]}
    assert "application/problem+json" in page["responses"]["422"]["content"]
    assert schema["paths"]["/api/v1/ready"]["get"]["security"] == []
