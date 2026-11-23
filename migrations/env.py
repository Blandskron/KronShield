"""Run PostgreSQL migrations with a dedicated migration database URL."""

import os

from alembic import context
from sqlalchemy import create_engine, make_url, pool


def run_migrations() -> None:
    url = make_url(os.environ["PENTEST_AGENT_MIGRATION_URL"])
    if url.drivername != "postgresql+psycopg":
        raise ValueError("PENTEST_AGENT_MIGRATION_URL must use postgresql+psycopg")

    if context.is_offline_mode():
        raise RuntimeError("These migrations must verify the runtime role against a live database")

    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, version_table="pentest_agent_alembic_version")
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
