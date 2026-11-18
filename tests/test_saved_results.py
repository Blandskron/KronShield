import errno
import json
from pathlib import Path
from unittest.mock import Mock

import dotenv
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from application.report_input import SavedAudit
from domain.models import Finding, FindingType
from infra import artifacts
from infra.db import Base
from infra.models import FindingORM, OfflineFindingORM, OfflineResultORM
from infra.repository import save_findings, save_offline_result


@pytest.fixture
def save_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dotenv, "load_dotenv", Mock())
    from main import app

    return lambda *args: CliRunner().invoke(app, ["audit", "save", *args])


@pytest.fixture
def capture():
    path = Path("capture.json")
    path.write_text(json.dumps({
        "url": "https://scope.example",
        "findings": [{
            "type": "sqli", "detail": "Firma observada", "url": "https://scope.example/search?q=test",
            "status": "observed", "confidence": "low", "extra": {"custom_evidence": {"id": "fixture"}},
        }],
    }), encoding="utf8")
    return path


def test_repeating_domain_preserves_results_and_observed_url(save_cli, capture):
    first, second = save_cli("-i", str(capture)), save_cli("-i", str(capture))
    assert first.exit_code == second.exit_code == 0
    a, b = json.loads(first.stdout), json.loads(second.stdout)
    assert a["result_id"] != b["result_id"]
    assert a["snapshot"] != b["snapshot"]
    assert Path(a["snapshot"]).is_file() and Path(b["snapshot"]).is_file()
    engine = create_engine("sqlite:///pentest.db")
    try:
        with Session(engine) as db:
            results = db.scalars(select(OfflineResultORM)).all()
            findings = db.scalars(select(OfflineFindingORM)).all()
            assert len(results) == len(findings) == 2
            assert {result.url for result in results} == {"https://scope.example"}
            assert {finding.observed_url for finding in findings} == {"https://scope.example/search?q=test"}
            assert all(finding.status == "observed" and finding.confidence == "low" for finding in findings)
            assert all(finding.extra["custom_evidence"]["id"] == "fixture" for finding in findings)
    finally:
        engine.dispose()


def test_commit_failure_rolls_back_and_retry_deduplicates_database(save_cli, capture, monkeypatch):
    original = Session.commit
    monkeypatch.setattr(Session, "commit", Mock(side_effect=OperationalError("fixture", {}, RuntimeError())))
    failed = save_cli("-i", str(capture))
    assert failed.exit_code == 5
    partial = json.loads(failed.stdout)
    assert partial["persistence"] == "json_only"
    saved = Path(partial["snapshot"])
    assert SavedAudit.model_validate_json(saved.read_bytes()).result_id is not None
    engine = create_engine("sqlite:///pentest.db")
    try:
        with Session(engine) as db:
            assert db.scalars(select(OfflineResultORM)).all() == []
            assert db.scalars(select(OfflineFindingORM)).all() == []
    finally:
        engine.dispose()
    monkeypatch.setattr(Session, "commit", original)
    for _ in range(2):
        retried = save_cli("-i", str(saved))
        assert retried.exit_code == 0, retried.output
        assert json.loads(retried.stdout)["result_id"] == partial["result_id"]
    engine = create_engine("sqlite:///pentest.db")
    try:
        with Session(engine) as db:
            assert len(db.scalars(select(OfflineResultORM)).all()) == 1
            assert len(db.scalars(select(OfflineFindingORM)).all()) == 1
    finally:
        engine.dispose()


def test_disk_full_leaves_no_database_or_partial_file(save_cli, capture, monkeypatch):
    monkeypatch.setattr(artifacts.os, "fsync", Mock(side_effect=OSError(errno.ENOSPC, "fixture disk full")))
    failed = save_cli("-i", str(capture))
    assert failed.exit_code == 5
    assert not Path("pentest.db").exists()
    assert list(Path("results").iterdir()) == []


def test_legacy_database_survives_new_offline_tables(save_cli, capture):
    engine = create_engine("sqlite:///pentest.db")
    try:
        FindingORM.__table__.create(engine)
        with Session(engine) as db:
            save_findings(db, [Finding(FindingType.INFO, "legacy detail")], "https://legacy.example")
    finally:
        engine.dispose()
    assert save_cli("-i", str(capture)).exit_code == 0
    engine = create_engine("sqlite:///pentest.db")
    try:
        with Session(engine) as db:
            legacy, = db.scalars(select(FindingORM)).all()
            assert legacy.detail == "legacy detail"
            assert legacy.url == "https://legacy.example"
    finally:
        engine.dispose()


def test_repository_rejects_reuse_of_identity_with_different_snapshot():
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            snapshot = {"result_id": "fixture-id", "url": "https://scope.example", "findings": []}
            save_offline_result(db, snapshot, "a" * 64)
            with pytest.raises(ValueError, match="different snapshot"):
                save_offline_result(db, snapshot, "b" * 64)
            assert len(db.scalars(select(OfflineResultORM)).all()) == 1
    finally:
        engine.dispose()


def test_failed_finding_insert_rolls_back_result_and_previous_findings():
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            snapshot = {
                "result_id": "fixture-id", "url": "https://scope.example",
                "findings": [{"type": "info", "detail": "first"}, {"type": None, "detail": "invalid"}],
            }
            with pytest.raises(IntegrityError):
                save_offline_result(db, snapshot, "a" * 64)
            assert db.scalars(select(OfflineResultORM)).all() == []
            assert db.scalars(select(OfflineFindingORM)).all() == []
            snapshot["findings"][1]["type"] = "info"
            save_offline_result(db, snapshot, "b" * 64)
            assert len(db.scalars(select(OfflineFindingORM)).all()) == 2
    finally:
        engine.dispose()
