"""Bind verified tenant context to a single PostgreSQL transaction."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, Engine, text


@contextmanager
def tenant_transaction(
    engine: Engine,
    *,
    org_id: UUID | None,
    user_id: UUID,
    project_id: UUID | None = None,
) -> Iterator[Connection]:
    """Use a runtime-role engine and IDs resolved from authenticated membership."""
    with engine.begin() as connection:
        connection.execute(text("""
            SELECT set_config('pentest_agent.org_id', :org_id, true),
                   set_config('pentest_agent.user_id', :user_id, true),
                   set_config('pentest_agent.project_id', :project_id, true)
        """), {
            "org_id": str(org_id) if org_id is not None else "",
            "user_id": str(user_id),
            "project_id": str(project_id) if project_id is not None else "",
        })
        yield connection
