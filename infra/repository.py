from domain.models import Finding
from infra.models import FindingORM, OfflineFindingORM, OfflineResultORM
from sqlalchemy.orm import Session


def save_findings(db: Session, findings: list[Finding], url: str):
    """
    Persists a list of Finding objects to the database using the ORM model.

    Args:
        db (Session): Active SQLAlchemy session.
        findings (list[Finding]): List of findings to persist.
        url (str): URL associated with the findings.
    """
    try:
        for finding in findings:
            orm = FindingORM(
                url=url,
                type=finding.type,
                detail=finding.detail,
                payload=finding.payload,
                extra=finding.extra,
            )
            db.add(orm)
        db.commit()
    except Exception:
        db.rollback()
        raise


def save_offline_result(db: Session, snapshot: dict, digest: str) -> None:
    """Commit all records once, or restore the session after any failure."""
    try:
        result_id = snapshot["result_id"]
        existing = db.get(OfflineResultORM, result_id)
        if existing is not None:
            if existing.sha256 != digest:
                raise ValueError("Result identity already belongs to a different snapshot")
            return
        db.add(OfflineResultORM(
            id=result_id, url=snapshot["url"], sha256=digest, snapshot=snapshot,
        ))
        db.flush()
        for position, finding in enumerate(snapshot["findings"]):
            db.add(OfflineFindingORM(
                result_id=result_id, position=position, observed_url=finding.get("url"),
                type=finding["type"], detail=finding["detail"], payload=finding.get("payload"),
                extra=finding.get("extra"), status=finding.get("status"), confidence=finding.get("confidence"),
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
