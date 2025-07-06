from domain.models import Finding
from infra.models import FindingORM
from sqlalchemy.orm import Session
import json

def save_findings(db: Session, findings: list[Finding], url: str):
    for finding in findings:
        orm = FindingORM(
            url=url,
            type=finding.type,
            detail=finding.detail,
            payload=finding.payload,
            extra=finding.extra
        )
        db.add(orm)
    db.commit()