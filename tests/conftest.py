"""Shared test setup.

Database tests run twice: once on a throwaway SQLite file, and once on Postgres if
TEST_DATABASE_URL is set (otherwise the Postgres run just gets skipped). Easiest way:

    docker compose up -d db
    TEST_DATABASE_URL=postgresql://aj:aj@localhost:5432/ajindex python3 -m pytest -q
"""

import os

import pytest

PG_URL = os.environ.get( "TEST_DATABASE_URL" )


def _wipe_postgres( url ):
    import psycopg
    with psycopg.connect( url, autocommit=True ) as c:
        # start every test from nothing so tests can't leak into each other
        c.execute( "DROP VIEW IF EXISTS listings, current_worth" )
        c.execute( "DROP TABLE IF EXISTS comments, comment_progress, worth_snapshots, pages" )


@pytest.fixture( params=[ "sqlite", "postgres" ] )
def db_target( request, tmp_path ):
    if request.param == "sqlite":
        return tmp_path / "w.db"
    if not PG_URL:
        pytest.skip( "set TEST_DATABASE_URL to also test on Postgres" )
    _wipe_postgres( PG_URL )
    return PG_URL
