import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from application.access import AccessError
from application.evidence import Source, project_upload


FIXTURE = Path(__file__).with_name("fixtures") / "yellow-sarif-2.1.0.json"
PROVENANCE = {
    "producer": "fixture-ci", "producer_version": "1.2.0",
    "repository_uri": "https://git.example.test/team/service.git", "revision_id": "1" * 40,
}


def permitted(payload, **changes):
    return Source(**{
        "kind": "sarif-v1", "target_id": uuid4(), "digest": sha256(payload).hexdigest(), "size_bytes": len(payload),
        "classification": "internal", "capability": "code-review", "sarif_provenance": PROVENANCE, **changes,
    })


def test_project_sarif_without_opening_a_path_or_resolving_a_uri(monkeypatch):
    payload = FIXTURE.read_bytes()
    source = permitted(payload)

    def unexpected_call(*args, **kwargs):
        pytest.fail("The SARIF reader must not open evidence locations")

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "open", unexpected_call)
        guarded.setattr("builtins.open", unexpected_call)
        projection = project_upload(source, payload)
    assert projection == {
        "target_id": str(source.target_id), "sarif_version": "2.1.0", "provenance": PROVENANCE,
        "locations": [{"rule_id": "review.config.required", "path": "src/config.py", "start_line": 12, "end_line": 14}],
    }


@pytest.mark.parametrize("path", [
    "/src/config.py", "C:/src/config.py", "src\\config.py", "../config.py", "src/./config.py",
    "src/%2e%2e/config.py", "//git.example.test/src/config.py", "https://git.example.test/src/config.py",
    "src/config.py?query=1", "src/config.py#frag", "src//config.py",
])
def test_sarif_rejects_noncanonical_locations(path):
    document = json.loads(FIXTURE.read_bytes())
    location = document["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    location["artifactLocation"]["uri"] = path
    payload = json.dumps(document).encode()
    with pytest.raises(AccessError, match="invalid_evidence_source"):
        project_upload(permitted(payload), payload)


@pytest.mark.parametrize(("scope", "field", "value"), [
    ("document", "$schema", "https://untrusted.example.test/sarif.json"),
    ("run", "originalUriBaseIds", {}),
    ("run", "externalPropertyFileReferences", {}),
    ("result", "baselineState", "unchanged"),
    ("result", "relatedLocations", []),
    ("artifact", "uriBaseId", "SRCROOT"),
    ("artifact", "index", 0),
])
def test_sarif_rejects_external_relationships(scope, field, value):
    document = json.loads(FIXTURE.read_bytes())
    run = document["runs"][0]
    result = run["results"][0]
    artifact = result["locations"][0]["physicalLocation"]["artifactLocation"]
    {"document": document, "run": run, "result": result, "artifact": artifact}[scope][field] = value
    payload = json.dumps(document).encode()
    with pytest.raises(AccessError, match="invalid_evidence_source"):
        project_upload(permitted(payload), payload)


@pytest.mark.parametrize("field", list(PROVENANCE))
def test_sarif_provenance_must_match_permission(field):
    payload = FIXTURE.read_bytes()
    changes = {"producer": "other-ci", "producer_version": "9.0", "repository_uri": "https://git.example.test/other",
               "revision_id": "2" * 40}
    source = permitted(payload, sarif_provenance={**PROVENANCE, field: changes[field]})
    with pytest.raises(AccessError, match="evidence_sarif_provenance_mismatch"):
        project_upload(source, payload)


def test_sarif_rejects_ambiguous_documents_and_excess_results():
    data = FIXTURE.read_bytes()
    observed = json.loads(data)
    run = observed["runs"][0]
    run["results"] *= 501
    redundant = json.dumps(observed, separators=(",", ":")).encode()
    for raw in (redundant, data.replace(b'"version": "2.1.0",', b'"version": "2.1.0", "version": "2.1.0",'),
                b"[" * 2000, data + b"\xff"):
        with pytest.raises(AccessError, match="invalid_evidence_source"):
            project_upload(permitted(raw), raw)
    with pytest.raises(AccessError, match="evidence_source_mismatch"):
        project_upload(permitted(data), data + b" ")
    with pytest.raises(ValidationError):
        permitted(data, sarif_provenance=None)
    with pytest.raises(ValidationError):
        permitted(data, capability="event-review")
