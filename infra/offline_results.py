"""SQLite destination for local saved results, including preexisting databases."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from infra.models import OfflineFindingORM, OfflineResultORM
from infra.repository import save_offline_result


def persist_offline_result(database: Path, snapshot: dict, digest: str) -> None:
    engine = create_engine(URL.create("sqlite", database=str(database.resolve())))
    try:
        # Add only the offline tables. The legacy findings table is preserved.
        OfflineResultORM.__table__.create(engine, checkfirst=True)
        OfflineFindingORM.__table__.create(engine, checkfirst=True)
        with Session(engine) as session:
            save_offline_result(session, snapshot, digest)
    finally:
        engine.dispose()
