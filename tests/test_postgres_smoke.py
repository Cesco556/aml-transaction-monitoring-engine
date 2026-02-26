"""Optional Postgres smoke test; run only when POSTGRES_TEST_URL is set."""

import os

import pytest
from sqlalchemy import text

from aml_monitoring.db import init_db, session_scope

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")


@pytest.mark.skipif(
    not POSTGRES_TEST_URL or "postgresql" not in (POSTGRES_TEST_URL or ""),
    reason="POSTGRES_TEST_URL (postgresql URL) not set",
)
def test_postgres_connect_and_query() -> None:
    """Minimal smoke test: connect to Postgres and run a query."""
    init_db(POSTGRES_TEST_URL, echo=False)
    with session_scope() as session:
        row = session.execute(text("SELECT 1 AS n")).first()
    assert row is not None
    assert row[0] == 1
