"""Initialize private pilot volumes and run schema migrations."""

import os
import sys
from base64 import b64encode
from pathlib import Path
from secrets import token_urlsafe

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import URL


ROOT = Path("/run/pilot")
APP_UID = 10001


def secret(path: Path, contents: str, uid: int, gid: int) -> None:
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(contents + "\n")
        os.chown(path, uid, gid)


def seed() -> None:
    for name, uid in (("app", APP_UID), ("db", 999), ("objects", APP_UID)):
        directory = ROOT / name
        directory.mkdir(exist_ok=True)
        os.chown(directory, uid, APP_UID)
        directory.chmod(0o750)
    secret(ROOT / "db/admin", token_urlsafe(32), 999, APP_UID)
    secret(ROOT / "db/migrator", token_urlsafe(32), 999, APP_UID)
    secret(ROOT / "app/runtime", token_urlsafe(32), APP_UID, APP_UID)
    secret(ROOT / "app/bootstrap", token_urlsafe(32), APP_UID, APP_UID)
    secret(ROOT / "app/document-key", b64encode(os.urandom(32)).decode(), APP_UID, APP_UID)
    secret(ROOT / "objects/password", token_urlsafe(32), APP_UID, APP_UID)
    object_directory = Path("/objects-data/filerldb2")
    object_directory.mkdir(exist_ok=True)
    for path in (Path("/cli-state"), Path("/objects-data"), object_directory):
        os.chown(path, APP_UID, APP_UID)
        path.chmod(0o700)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="ascii").strip()


def migrate() -> None:
    with psycopg.connect(host="postgres", dbname="pentest", user="postgres", password=read("db/admin")) as connection:
        for role, password in (
            ("pentest_agent_runtime", None),
            ("pentest_login", read("app/runtime")),
            ("pentest_migrator", read("db/migrator")),
        ):
            if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                declaration = sql.SQL("NOLOGIN") if password is None else sql.SQL("LOGIN PASSWORD {}").format(sql.Literal(password))
                connection.execute(sql.SQL("CREATE ROLE {} {} NOSUPERUSER NOBYPASSRLS")
                                   .format(sql.Identifier(role), declaration))
        connection.execute("GRANT pentest_agent_runtime TO pentest_login")
        connection.execute("GRANT CREATE ON DATABASE pentest TO pentest_migrator")
        connection.execute("GRANT CREATE ON SCHEMA public TO pentest_migrator")
    url = URL.create("postgresql+psycopg", username="pentest_migrator", password=read("db/migrator"),
                     host="postgres", database="pentest")
    os.environ["PENTEST_AGENT_MIGRATION_URL"] = url.render_as_string(hide_password=False)
    command.upgrade(Config("/app/alembic.ini"), "head")


if __name__ == "__main__":
    {"seed": seed, "migrate": migrate}[sys.argv[1]]()
