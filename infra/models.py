from sqlalchemy import Column, Integer, String, Text, Enum, JSON, ForeignKey, UniqueConstraint

from infra.db import Base
from domain.models import FindingType


class FindingORM(Base):
    """
    ORM model for storing security findings in the database.

    Maps to the 'findings' table and supports INFO, PORT, XSS, SQLI and ERROR.
    """
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(255), nullable=False)
    type = Column(Enum(FindingType), nullable=False)
    detail = Column(Text, nullable=False)
    payload = Column(Text)
    extra = Column(JSON)


class OfflineResultORM(Base):
    __tablename__ = "offline_results"

    id = Column(String(36), primary_key=True)
    url = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)


class OfflineFindingORM(Base):
    __tablename__ = "offline_findings"
    __table_args__ = (UniqueConstraint("result_id", "position"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    result_id = Column(String(36), ForeignKey("offline_results.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    observed_url = Column(Text)
    type = Column(String(64), nullable=False)
    detail = Column(Text, nullable=False)
    payload = Column(Text)
    extra = Column(JSON)
    status = Column(String(32))
    confidence = Column(String(32))
