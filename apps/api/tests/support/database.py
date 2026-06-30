# apps/api/tests/support/database.py

"""Database helpers for API tests."""

import os

import pytest
from sqlalchemy.engine import make_url

TEST_DATABASE_URL_ENV_VAR = "TEST_DATABASE_URL"


def require_test_database_url() -> str:
    """Return the configured PostgreSQL test database URL or skip the test."""
    database_url = os.getenv(TEST_DATABASE_URL_ENV_VAR)
    if not database_url:
        pytest.skip(f"Set {TEST_DATABASE_URL_ENV_VAR} to run database-backed API tests")

    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        pytest.fail("API database tests must use PostgreSQL, not SQLite")

    return database_url


def make_async_test_database_url(database_url: str) -> str:
    """Return an asyncpg SQLAlchemy URL for the configured PostgreSQL test database."""
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)
