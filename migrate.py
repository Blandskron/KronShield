from infra.db import Base, engine
from infra.models import FindingORM

Base.metadata.create_all(bind=engine)
