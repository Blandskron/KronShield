from sqlalchemy import Column, Integer, String, Text, Enum, JSON
from sqlalchemy.ext.declarative import declarative_base
from domain.models import FindingType

Base = declarative_base()

class FindingORM(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(255), nullable=False)
    type = Column(Enum(FindingType), nullable=False)
    detail = Column(Text, nullable=False)
    payload = Column(Text)
    extra = Column(JSON)
