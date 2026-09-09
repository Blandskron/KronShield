from sqlalchemy import Column, Integer, String, Text, Enum, JSON

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
