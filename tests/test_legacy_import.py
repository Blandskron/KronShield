import json
import sqlite3
from contextlib import closing
from hashlib import sha256
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from application.legacy_import import FileFormat, parse_source, read_source
from main import app


def test_import_json_dry_run_preserves_source(tmp_path):
    source = tmp_path / "results.json"
    raw = b'{"url":"https://target.example","findings":[{"type":"info","detail":"historical","url":"https://target.example/a","confidence":"medium"}]}'
    source.write_bytes(raw)
    batch = parse_source(raw, FileFormat.JSON)
    assert batch.source_digest == sha256(raw).hexdigest()
    assert batch.findings[0]["reported_confidence"] == "medium"
    assert batch.findings[0]["confidence"] == "unverified"
    result = CliRunner().invoke(app, ["audit", "import-legacy", "--input", str(source), "--format", "json",
                                      "--org-id", str(uuid4()), "--project-id", str(uuid4()), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["finding_count"] == 1
    assert source.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [source]


def test_import_mixed_sqlite_retains_both_formats_and_missing_observed_url(tmp_path):
    path = tmp_path / "old.db"
    result_id = str(uuid4())
    snapshot = {"result_id": result_id, "url": "https://new.example",
                "findings": [{"type": "xss", "detail": "unverified", "url": "https://new.example/location"}]}
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE findings(id INTEGER PRIMARY KEY, url TEXT, type TEXT, detail TEXT)")
        db.execute("INSERT INTO findings VALUES (3, 'https://old.example', 'INFO', 'legacy evidence')")
        db.execute("CREATE TABLE offline_results(id TEXT PRIMARY KEY, snapshot TEXT)")
        db.execute("INSERT INTO offline_results VALUES (?, ?)", (result_id, json.dumps(snapshot)))
        db.commit()
    raw = read_source(path, FileFormat.SQLITE)
    batch = parse_source(raw, FileFormat.SQLITE)
    assert len(batch.findings) == 2
    observed, saved = batch.findings
    assert observed["record_key"] == "findings/3"
    assert observed["target_url"] == "https://old.example" and observed["observed_url"] is None
    assert saved["record_key"] == f"offline_results/{result_id}/0"
    assert saved["observed_url"] == "https://new.example/location"
    assert path.read_bytes() == raw


@pytest.mark.parametrize("kind", list(FileFormat))
def test_invalid_source_is_rejected(kind):
    with pytest.raises(ValueError, match="Invalid"):
        parse_source(b"not a valid source", kind)
