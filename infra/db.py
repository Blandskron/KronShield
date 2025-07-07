from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# -----------------------------------------------------------------------------
# Database configuration using SQLite and SQLAlchemy ORM.
# -----------------------------------------------------------------------------


DATABASE_URL = "sqlite:///pentest.db"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
