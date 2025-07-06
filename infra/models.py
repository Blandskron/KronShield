from sqlalchemy import Column, Integer, String, Text
from infra.db import Base

class FindingORM(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50))
    detail = Column(Text)
    url = Column(Text, nullable=True)
    payload = Column(Text, nullable=True)
    extra = Column(Text, nullable=True)
