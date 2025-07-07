from infra.db import Base, engine
from infra.models import FindingORM

# -----------------------------------------------------------------------------
# Initializes the database schema by creating all declared tables.
# This should be run once during setup or migration to ensure schema exists.
# -----------------------------------------------------------------------------


Base.metadata.create_all(bind=engine)
