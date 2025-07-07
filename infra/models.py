from sqlalchemy import Column, Integer, String, Text, Enum, JSON
from sqlalchemy.ext.declarative import declarative_base
from domain.models import FindingType

Base = declarative_base()

class FindingORM(Base):
    """
    ORM model for storing security findings in the database.

    Maps directly to the 'findings' table and supports types such as XSS, SQLi, open ports, and errors.

    Attributes:
        id (int): Primary key, auto-incremented.
        url (str): Target URL where the finding was detected.
        type (FindingType): Type of finding (e.g., INFO, XSS, SQLI).
        detail (str): Description of the issue found.
        payload (str): The attack vector or test string used (if applicable).
        extra (JSON): Additional metadata (headers, port info, etc.).
    """
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(255), nullable=False)
    type = Column(Enum(FindingType), nullable=False)
    detail = Column(Text, nullable=False)
    payload = Column(Text)
    extra = Column(JSON)
