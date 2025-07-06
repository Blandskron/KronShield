from sqlalchemy.orm import Session
from domain.models import Finding
from infra.models import FindingORM

def save_findings(db: Session, findings: list[Finding]):
    for f in findings:
        db_finding = FindingORM(
            type=f.type.value,
            detail=f.detail,
            url=f.url,
            payload=f.payload,
            extra=str(f.extra) if f.extra else None
        )
        db.add(db_finding)
    db.commit()
