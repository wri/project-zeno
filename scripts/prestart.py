"""Create this deployment's database from a template, if it does not exist yet.

Every deployment gets its own database on a shared Postgres instance, cloned from
a read-only template that already holds the reference data. Cloning is fast and
gives each deployment a known starting schema version, so migrations only ever
run forward.

Runs before the API server starts. Creates only -- dropping is teardown's job,
since other deployments share the instance.
"""

import os
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# CREATE DATABASE cannot run inside a transaction, and Postgres refuses to clone
# a database that has any open connections -- including this one. Both are why
# the work happens from a separate maintenance database.
MAINTENANCE_DATABASE = "template1"


def database_name_from_url(url: str) -> str:
    """Return the database name in *url*, rejecting an empty one."""
    name = urlsplit(url).path.lstrip("/")
    if not name:
        raise ValueError(f"no database name in DATABASE_URL: {url!r}")
    return name


def maintenance_url(url: str) -> str:
    """Rewrite *url* to reach the maintenance database over psycopg2."""
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0]
    return urlunsplit(
        (
            scheme,
            parts.netloc,
            f"/{MAINTENANCE_DATABASE}",
            parts.query,
            parts.fragment,
        )
    )


def database_exists(cursor, name: str) -> bool:
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
    return cursor.fetchone() is not None


def clone_database(url: str, template: str) -> bool:
    """Clone *template* into the database named by *url*.

    Returns True if it created one. Safe to re-run: an existing database is left
    untouched, so a restart does not discard its data.
    """
    name = database_name_from_url(url)

    connection = psycopg2.connect(maintenance_url(url))
    try:
        connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with connection.cursor() as cursor:
            if database_exists(cursor, name):
                print(f"database {name} already exists")
                return False

            if not database_exists(cursor, template):
                raise SystemExit(
                    f"template database {template!r} does not exist"
                )

            print(f"creating database {name} from template {template}")
            cursor.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(name), sql.Identifier(template)
                )
            )
            return True
    finally:
        connection.close()


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    clone_database(
        url, os.environ.get("SEED_TEMPLATE_DATABASE", "horizon_seed")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
